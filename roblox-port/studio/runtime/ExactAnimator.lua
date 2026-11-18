--!native
-- SPSO ExactAnimator: plays a hero's ORIGINAL animation curves exactly the way Unity's legacy
-- Animation component did: Hermite curves, quaternion components normalised, the full node chain,
-- crossfades, wrap modes, animation events, facial expressions (FacialAnimation.cs) and root motion
-- (CharacterMotionController.performRootMotion).
--
-- Output on clients:
--   * pose without visible bone scale -> Roblox Bones (Bone.Transform) of the imported skinned model
--   * pose WITH bone scale (fists swelling etc.) -> an EditableMesh copy skinned on the CPU from the
--     same pose (Roblox bones cannot scale); the imported mesh is hidden meanwhile.
-- Headless mode (server, or no model): time, events and root motion only.
--
-- local a = ExactAnimator.new(HeroPack.get("ElRugido"), model, config); a:Start()
-- a:CrossFade("attack_L1", 0.1); a.Event:Connect(function(fn, data, clipName, ev) ... end)
local AssetService = game:GetService("AssetService")
local ContentProvider = game:GetService("ContentProvider")
local RunService = game:GetService("RunService")

local ExactAnimator = {}
ExactAnimator.__index = ExactAnimator

local WrapMode = { Default = 0, Once = 1, Loop = 2, PingPong = 4, ClampForever = 8 }
ExactAnimator.WrapMode = WrapMode
local FACES = { normal = 0, happy = 1, surprised = 2, aggressive = 3, squint = 4, blink = 5, custom1 = 6, custom2 = 7 }
ExactAnimator.Faces = FACES
local HUGE = math.huge

-- tiny signal ---------------------------------------------------------------------------------
local Signal = {}
Signal.__index = Signal
function Signal.new() return setmetatable({ _fns = {} }, Signal) end
function Signal:Connect(fn)
	local fns = self._fns
	table.insert(fns, fn)
	return { Disconnect = function() local i = table.find(fns, fn); if i then table.remove(fns, i) end end }
end
function Signal:Fire(...)
	for _, fn in table.clone(self._fns) do task.spawn(fn, ...) end
end
ExactAnimator.Signal = Signal

-- Unity AnimationCurve evaluation of one curve at time t into out[1..dim] -------------------------
local function evalCurve(buf: buffer, cv, t: number, cursors, ci: number, out)
	local dim = cv.dim
	local const = cv.const
	if const then
		for d = 1, dim do out[d] = const[d] end
		return
	end
	local times, n, vOff = cv.times, cv.n, cv.vOff
	if n == 1 or t <= times[1] then
		for d = 0, dim - 1 do out[d + 1] = buffer.readf32(buf, vOff + d * 4) end
		return
	elseif t >= times[n] then
		local o = vOff + (n - 1) * dim * 4
		for d = 0, dim - 1 do out[d + 1] = buffer.readf32(buf, o + d * 4) end
		return
	end
	local i = cursors[ci] or 1
	if i < 1 or i > n - 1 or times[i] > t then
		local lo, hi = 1, n - 1
		while lo < hi do
			local mid = (lo + hi + 1) // 2
			if times[mid] <= t then lo = mid else hi = mid - 1 end
		end
		i = lo
	else
		while i < n - 1 and times[i + 1] <= t do i += 1 end
	end
	cursors[ci] = i
	local t0 = times[i]
	local dt = times[i + 1] - t0
	local o0 = vOff + (i - 1) * dim * 4
	if dt <= 0 then
		for d = 0, dim - 1 do out[d + 1] = buffer.readf32(buf, o0 + d * 4) end
		return
	end
	local u = (t - t0) / dt
	local u2 = u * u
	local u3 = u2 * u
	local h00, h10, h01, h11 = 2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2
	local o1 = o0 + dim * 4
	local so = cv.outOffs[i]
	local si = cv.inOff + i * dim * 4 -- in slope of key i+1
	for d = 0, dim - 1 do
		local v0 = buffer.readf32(buf, o0 + d * 4)
		local m0 = buffer.readf32(buf, so + d * 4) * dt
		local m1 = buffer.readf32(buf, si + d * 4) * dt
		local r = h00 * v0 + h10 * m0 + h01 * buffer.readf32(buf, o1 + d * 4) + h11 * m1
		if r ~= r or r == HUGE or r == -HUGE or m0 ~= m0 or m1 ~= m1 or m0 == HUGE or m0 == -HUGE or m1 == HUGE or m1 == -HUGE then
			r = v0 -- stepped key
		end
		out[d + 1] = r
	end
end
ExactAnimator.evalCurve = evalCurve

-- construction -------------------------------------------------------------------------------------
function ExactAnimator.new(pack, model: Model?, config)
	config = config or {}
	local self = setmetatable({}, ExactAnimator)
	self.pack, self.model, self.config = pack, model, config
	self.headless = model == nil or config.headless == true
	local N = #pack.nodes
	self.N = N
	local RT, RQ, RS, parent = table.create(3 * N), table.create(4 * N), table.create(3 * N), table.create(N)
	for i, n in pack.nodes do
		RT[3 * i - 2], RT[3 * i - 1], RT[3 * i] = n.t[1], n.t[2], n.t[3]
		RQ[4 * i - 3], RQ[4 * i - 2], RQ[4 * i - 1], RQ[4 * i] = n.q[1], n.q[2], n.q[3], n.q[4]
		RS[3 * i - 2], RS[3 * i - 1], RS[3 * i] = n.s[1], n.s[2], n.s[3]
		parent[i] = n.parent
	end
	self.RT, self.RQ, self.RS, self.parent = RT, RQ, RS, parent
	self.LT, self.LQ, self.LS = table.create(3 * N, 0), table.create(4 * N, 0), table.create(3 * N, 0)
	self.ST, self.SQ, self.SS = table.create(3 * N, 0), table.create(4 * N, 0), table.create(3 * N, 0)
	self.W = table.create(12 * N, 0)
	self.SM = table.create(12 * #pack.bones, 0)
	self.tmp = table.create(4, 0)
	self.states, self.active, self.pending = {}, {}, {}
	self.clock = 0
	self.Event = Signal.new()
	self.wrapDefaults = config.wrapModes or {}
	self.face, self.faceDefault, self.faceRevertAt = 0, 0, 0
	self.rootNode = pack.nodeIndex.motion_export
	self.rootForward, self.rootPrevY = 0, nil
	self.mode = "bones"
	if not self.headless then self:_bindRig(model) end
	return self
end

function ExactAnimator:_bindRig(model: Model)
	local pack, config = self.pack, self.config
	local root = config.rigRoot or model:FindFirstChild("RootPart", true)
	assert(root, "hero model has no RootPart")
	self.rigRoot = root
	local byName = {}
	for _, d in root:GetDescendants() do
		if d:IsA("Bone") then byName[d.Name] = d end
	end
	local NB = #pack.bones
	self.rigBones, self.rigParent, self.boneCFInv = table.create(NB), table.create(NB, 0), table.create(NB)
	self.C, self.A = table.create(12 * NB, 0), table.create(NB)
	local depth = {}
	for b, pb in pack.bones do
		local bone = byName[pb.name]
		assert(bone, "rig has no bone " .. pb.name)
		self.rigBones[b] = bone
		local par = bone.Parent
		self.rigParent[b] = (par and par:IsA("Bone")) and (pack.boneIndex[par.Name] or 0) or 0
		self.boneCFInv[b] = bone.CFrame:Inverse()
		local rest, p, d = bone.CFrame, bone.Parent, 0
		while p and p:IsA("Bone") do
			rest = p.CFrame * rest
			p = p.Parent
			d += 1
		end
		depth[b] = d
		local x, y, z, r00, r01, r02, r10, r11, r12, r20, r21, r22 = rest:GetComponents()
		local m, c = pb.binv, (b - 1) * 12
		local C = self.C
		for row = 0, 2 do -- C = Binv * Rest
			local a0, a1, a2, a3 = m[row * 4 + 1], m[row * 4 + 2], m[row * 4 + 3], m[row * 4 + 4]
			C[c + row * 4 + 1] = a0 * r00 + a1 * r10 + a2 * r20
			C[c + row * 4 + 2] = a0 * r01 + a1 * r11 + a2 * r21
			C[c + row * 4 + 3] = a0 * r02 + a1 * r12 + a2 * r22
			C[c + row * 4 + 4] = a0 * x + a1 * y + a2 * z + a3
		end
	end
	local order = {}
	for b = 1, NB do order[b] = b end
	table.sort(order, function(a, b) return depth[a] < depth[b] end)
	self.boneOrder = order
	self.rigParts, self.rigTransparency = {}, {}
	for _, part in pack.parts do
		local mp = model:FindFirstChild(part.name, true)
		if mp then
			self.rigParts[part.name] = mp
			self.rigTransparency[mp] = mp.Transparency
		end
	end
	self.faceIds = config.faceTextures
	self.headName = config.headPart
	if self.faceIds then
		task.spawn(function() pcall(ContentProvider.PreloadAsync, ContentProvider, self.faceIds) end)
	end
	self.skinEnabled = config.skin ~= false
	self.skinTolerance = config.skinTolerance or 0.002
	self.lodDistance = config.lodDistance or 120
	self.normalsEvery = config.normalsEvery or 1
	self.skinFrame = 0
	if self.skinEnabled and config.prebuildSkin ~= false then task.spawn(self._buildSkin, self) end
end

-- EditableMesh copy of the hero for frames that need bone scale
function ExactAnimator:_buildSkin()
	if self.skin ~= nil then return end
	self.skin = false
	local ok, err = pcall(function()
		local list = {}
		for _, part in self.pack.parts do
			local rigPart = self.rigParts[part.name]
			local em = AssetService:CreateEditableMesh()
			local pos, nrm, uv, tri = part.pos, part.nrm, part.uv, part.tri
			local vids, nids, uids = table.create(part.nV), table.create(part.nN), table.create(part.nUV)
			for v = 1, part.nV do vids[v] = em:AddVertex(Vector3.new(pos[3 * v - 2], pos[3 * v - 1], pos[3 * v])) end
			for k = 1, part.nN do nids[k] = em:AddNormal(Vector3.new(nrm[3 * k - 2], nrm[3 * k - 1], nrm[3 * k])) end
			for k = 1, part.nUV do uids[k] = em:AddUV(Vector2.new(uv[2 * k - 1], uv[2 * k])) end
			for t = 0, part.nT - 1 do
				local o = t * 9
				local f = em:AddTriangle(vids[tri[o + 1]], vids[tri[o + 2]], vids[tri[o + 3]])
				em:SetFaceNormals(f, { nids[tri[o + 4]], nids[tri[o + 5]], nids[tri[o + 6]] })
				em:SetFaceUVs(f, { uids[tri[o + 7]], uids[tri[o + 8]], uids[tri[o + 9]] })
			end
			local mp = AssetService:CreateMeshPartAsync(Content.fromObject(em))
			mp.Name = part.name .. "_Exact"
			mp.Size = mp.MeshSize
			mp.Anchored, mp.CanCollide, mp.CanQuery, mp.CanTouch, mp.Massless = false, false, false, false, true
			if rigPart then
				mp.TextureID = rigPart.TextureID
				mp.Material, mp.Color = rigPart.Material, rigPart.Color
			end
			mp.Transparency = 1
			mp.CFrame = self.rigRoot.CFrame
			local weld = Instance.new("WeldConstraint")
			weld.Part0, weld.Part1 = self.rigRoot, mp
			weld.Parent = mp
			mp.Parent = self.model
			table.insert(list, { part = part, em = em, mp = mp, vids = vids, nids = nids, rigPart = rigPart })
		end
		self.skin = list
		if self.faceIds and self.headName then
			for _, s in list do
				if s.part.name == self.headName then s.mp.TextureID = self.faceIds[self.face + 1] or s.mp.TextureID end
			end
		end
	end)
	if not ok then
		warn("[SPSO] exact skin unavailable, using bones only: " .. tostring(err))
		self.skin = false
	end
end

-- states (Unity AnimationState) --------------------------------------------------------------------
function ExactAnimator:HasClip(name: string): boolean
	return self.pack.clips[name] ~= nil
end

function ExactAnimator:GetState(name: string)
	local st = self.states[name]
	if st then return st end
	local clip = self.pack.clips[name]
	if not clip then return nil end
	local wrap = self.wrapDefaults[name] or clip.wrap
	if wrap == WrapMode.Default then wrap = WrapMode.Once end
	st = { name = name, clip = clip, length = clip.duration, time = 0, speed = 1, wrapMode = wrap,
		weight = 0, target = 0, fadeSpeed = HUGE, enabled = false, cursors = {} }
	self.states[name] = st
	return st
end

function ExactAnimator:_start(st)
	if st.enabled then return end
	st.enabled, st.justStarted, st.ended = true, true, false
	table.insert(self.active, st)
end

function ExactAnimator:_stop(st)
	st.enabled, st.weight, st.target, st.time, st.ended = false, 0, 0, 0, false
	local i = table.find(self.active, st)
	if i then table.remove(self.active, i) end
end

function ExactAnimator:IsPlaying(name: string): boolean
	local st = self.states[name]
	return st ~= nil and st.enabled
end

function ExactAnimator:Play(name: string): boolean
	local st = self:GetState(name)
	if not st then return false end
	for _, o in table.clone(self.active) do
		if o ~= st then self:_stop(o) end
	end
	self:_start(st)
	st.weight, st.target, st.fadeSpeed = 1, 1, HUGE
	return true
end

function ExactAnimator:CrossFade(name: string, fade: number?): boolean
	fade = fade or 0.3
	local st = self:GetState(name)
	if not st then return false end
	if fade <= 0 or #self.active == 0 or (#self.active == 1 and self.active[1] == st) then
		return self:Play(name)
	end
	self:_start(st)
	st.target = 1
	st.fadeSpeed = math.max(1e-6, 1 - st.weight) / fade
	for _, o in self.active do
		if o ~= st then
			o.target = 0
			o.fadeSpeed = math.max(1e-6, o.weight) / fade
		end
	end
	return true
end

function ExactAnimator:Stop(name: string?)
	if name then
		local st = self.states[name]
		if st and st.enabled then self:_stop(st) end
	else
		for _, o in table.clone(self.active) do self:_stop(o) end
	end
end

function ExactAnimator:Rewind(name: string?)
	for n, st in self.states do
		if name == nil or n == name then
			st.time, st.cursors = 0, {}
			if st.enabled then st.justStarted = true end
		end
	end
end

-- the clip that currently has the most weight (and is fading in)
function ExactAnimator:Current()
	local best
	for _, st in self.active do
		if st.target > 0 and (best == nil or st.weight > best.weight) then best = st end
	end
	return best
end

-- face (FacialAnimation.cs) ----------------------------------------------------------------------
function ExactAnimator:SetFace(k: number)
	if k == self.face then return end
	self.face = k
	if self.headless or not self.faceIds then return end
	local id = self.faceIds[k + 1]
	if not id then return end
	local rp = self.headName and self.rigParts[self.headName]
	if rp then rp.TextureID = id end
	if type(self.skin) == "table" then
		for _, s in self.skin do
			if s.part.name == self.headName then s.mp.TextureID = id end
		end
	end
end

function ExactAnimator:_faceTag(data: string)
	local expr, secs = string.match(data, "^%s*([%w_]+)%s*:?%s*([%d%.%-eE]*)")
	local k = expr and FACES[string.lower(expr)]
	if k then self:SetFace(k) end
	local s = tonumber(secs)
	if s and s > 0 then self.faceRevertAt = self.clock + s end
end

-- root motion: forward studs accumulated since the last call (performRootMotion semantics)
function ExactAnimator:ConsumeRootMotion(): number
	local d = self.rootForward
	self.rootForward = 0
	return d
end

-- frame update ---------------------------------------------------------------------------------------
local function sampleTime(st)
	local d = st.length
	local t = st.time
	if d <= 0 then return 0 end
	if st.wrapMode == WrapMode.Loop then
		return t % d
	elseif st.wrapMode == WrapMode.PingPong then
		local c = t % (2 * d)
		return c > d and 2 * d - c or c
	end
	return math.clamp(t, 0, d)
end

function ExactAnimator:_queueEvents(st, prev: number)
	local clip = st.clip
	local evs = clip.events
	local d = st.length
	if st.justStarted then
		prev = -1e-6 -- a state that just started fires everything from time 0 (catch-up after a late start)
		st.justStarted = false
	end
	local cur = st.time
	local function q(a, b)
		if st.target <= 0 then return end
		for _, e in evs do
			if e.time > a and e.time <= b and e.time <= d + 1e-5 then
				table.insert(self.pending, { st.name, e })
			end
		end
	end
	if st.wrapMode == WrapMode.Loop and d > 0 then
		if cur >= d then
			q(prev, d)
			cur %= d
			st.time = cur
			q(-1e-6, cur)
		else
			q(prev, cur)
		end
	elseif st.wrapMode == WrapMode.PingPong then
		return
	else
		q(prev, math.min(cur, d))
		if cur >= d and st.wrapMode == WrapMode.Once then st.ended = true end
	end
end

function ExactAnimator:_sample(st, T, Q, S)
	local N = self.N
	table.move(self.RT, 1, 3 * N, 1, T)
	table.move(self.RQ, 1, 4 * N, 1, Q)
	table.move(self.RS, 1, 3 * N, 1, S)
	local buf, t, cursors, tmp = self.pack.buf, sampleTime(st), st.cursors, self.tmp
	for ci, cv in st.clip.curves do
		evalCurve(buf, cv, t, cursors, ci, tmp)
		local n, kind = cv.node, cv.kind
		if kind == 0 then
			Q[4 * n - 3], Q[4 * n - 2], Q[4 * n - 1], Q[4 * n] = tmp[1], tmp[2], tmp[3], tmp[4]
		elseif kind == 1 then
			T[3 * n - 2], T[3 * n - 1], T[3 * n] = tmp[1], tmp[2], tmp[3]
		else
			S[3 * n - 2], S[3 * n - 1], S[3 * n] = tmp[1], tmp[2], tmp[3]
		end
	end
end

function ExactAnimator:_compose()
	local N, parent, W = self.N, self.parent, self.W
	local LT, LQ, LS = self.LT, self.LQ, self.LS
	for i = 1, N do
		local x, y, z, w = LQ[4 * i - 3], LQ[4 * i - 2], LQ[4 * i - 1], LQ[4 * i]
		local len = math.sqrt(x * x + y * y + z * z + w * w)
		if len > 1e-12 then x, y, z, w = x / len, y / len, z / len, w / len end
		local sx, sy, sz = LS[3 * i - 2], LS[3 * i - 1], LS[3 * i]
		local tx, ty, tz = LT[3 * i - 2], LT[3 * i - 1], LT[3 * i]
		local xx, yy, zz, xy, xz, yz, wx, wy, wz = x * x, y * y, z * z, x * y, x * z, y * z, w * x, w * y, w * z
		local b00, b01, b02 = (1 - 2 * (yy + zz)) * sx, 2 * (xy - wz) * sy, 2 * (xz + wy) * sz
		local b10, b11, b12 = 2 * (xy + wz) * sx, (1 - 2 * (xx + zz)) * sy, 2 * (yz - wx) * sz
		local b20, b21, b22 = 2 * (xz - wy) * sx, 2 * (yz + wx) * sy, (1 - 2 * (xx + yy)) * sz
		local o = (i - 1) * 12
		local p = parent[i]
		if p <= 0 then
			W[o + 1], W[o + 2], W[o + 3], W[o + 4] = b00, b01, b02, tx
			W[o + 5], W[o + 6], W[o + 7], W[o + 8] = b10, b11, b12, ty
			W[o + 9], W[o + 10], W[o + 11], W[o + 12] = b20, b21, b22, tz
		else
			local q = (p - 1) * 12
			for r = 0, 2 do
				local a0, a1, a2, a3 = W[q + r * 4 + 1], W[q + r * 4 + 2], W[q + r * 4 + 3], W[q + r * 4 + 4]
				W[o + r * 4 + 1] = a0 * b00 + a1 * b10 + a2 * b20
				W[o + r * 4 + 2] = a0 * b01 + a1 * b11 + a2 * b21
				W[o + r * 4 + 3] = a0 * b02 + a1 * b12 + a2 * b22
				W[o + r * 4 + 4] = a0 * tx + a1 * ty + a2 * tz + a3
			end
		end
	end
	-- skinning matrices S_b = W(node_b) * Binv_b
	local SM = self.SM
	for b, pb in self.pack.bones do
		local o, m, s = (pb.node - 1) * 12, pb.binv, (b - 1) * 12
		for r = 0, 2 do
			local a0, a1, a2, a3 = W[o + r * 4 + 1], W[o + r * 4 + 2], W[o + r * 4 + 3], W[o + r * 4 + 4]
			SM[s + r * 4 + 1] = a0 * m[1] + a1 * m[5] + a2 * m[9]
			SM[s + r * 4 + 2] = a0 * m[2] + a1 * m[6] + a2 * m[10]
			SM[s + r * 4 + 3] = a0 * m[3] + a1 * m[7] + a2 * m[11]
			SM[s + r * 4 + 4] = a0 * m[4] + a1 * m[8] + a2 * m[12] + a3
		end
	end
end

function ExactAnimator:_evaluate()
	local active, N = self.active, self.N
	local LT, LQ, LS = self.LT, self.LQ, self.LS
	local total, count, only = 0, 0, nil
	for _, st in active do
		if st.weight > 0 then
			total += st.weight
			count += 1
			only = st
		end
	end
	if count == 0 then return false end
	if count == 1 then
		self:_sample(only, LT, LQ, LS)
	else
		local ST, SQ, SS = self.ST, self.SQ, self.SS
		for k = 1, 3 * N do LT[k] = 0; LS[k] = 0 end
		for k = 1, 4 * N do LQ[k] = 0 end
		local first = true
		for _, st in active do
			if st.weight > 0 then
				self:_sample(st, ST, SQ, SS)
				local w = st.weight / total
				for i = 1, N do
					local a, b = 3 * i - 2, 4 * i - 3
					LT[a] += w * ST[a]; LT[a + 1] += w * ST[a + 1]; LT[a + 2] += w * ST[a + 2]
					LS[a] += w * SS[a]; LS[a + 1] += w * SS[a + 1]; LS[a + 2] += w * SS[a + 2]
					local sw = w
					if not first and (LQ[b] * SQ[b] + LQ[b + 1] * SQ[b + 1] + LQ[b + 2] * SQ[b + 2] + LQ[b + 3] * SQ[b + 3]) < 0 then
						sw = -w
					end
					LQ[b] += sw * SQ[b]; LQ[b + 1] += sw * SQ[b + 1]; LQ[b + 2] += sw * SQ[b + 2]; LQ[b + 3] += sw * SQ[b + 3]
				end
				first = false
			end
		end
	end
	self:_compose()
	return true
end

-- worst vertex error (studs) if bone scale/shear were dropped: decides bones vs exact skin
function ExactAnimator:_scaleError(): number
	local W, worst = self.W, 0
	for _, pb in self.pack.bones do
		local o = (pb.node - 1) * 12
		local c0x, c0y, c0z = W[o + 1], W[o + 5], W[o + 9]
		local c1x, c1y, c1z = W[o + 2], W[o + 6], W[o + 10]
		local c2x, c2y, c2z = W[o + 3], W[o + 7], W[o + 11]
		local d = math.max(math.abs(c0x * c0x + c0y * c0y + c0z * c0z - 1), math.abs(c1x * c1x + c1y * c1y + c1z * c1z - 1),
			math.abs(c2x * c2x + c2y * c2y + c2z * c2z - 1), 2 * math.abs(c0x * c1x + c0y * c1y + c0z * c1z),
			2 * math.abs(c0x * c2x + c0y * c2y + c0z * c2z), 2 * math.abs(c1x * c2x + c1y * c2y + c1z * c2z))
		local e = 0.5 * d * pb.radius
		if e > worst then worst = e end
	end
	return worst
end

function ExactAnimator:_applyBones()
	local W, C, A, pack = self.W, self.C, self.A, self.pack
	for _, b in self.boneOrder do
		local o, c = (pack.bones[b].node - 1) * 12, (b - 1) * 12
		local m = table.create(12)
		for r = 0, 2 do
			local w0, w1, w2, w3 = W[o + r * 4 + 1], W[o + r * 4 + 2], W[o + r * 4 + 3], W[o + r * 4 + 4]
			m[r * 4 + 1] = w0 * C[c + 1] + w1 * C[c + 5] + w2 * C[c + 9]
			m[r * 4 + 2] = w0 * C[c + 2] + w1 * C[c + 6] + w2 * C[c + 10]
			m[r * 4 + 3] = w0 * C[c + 3] + w1 * C[c + 7] + w2 * C[c + 11]
			m[r * 4 + 4] = w0 * C[c + 4] + w1 * C[c + 8] + w2 * C[c + 12] + w3
		end
		local cf = CFrame.new(m[4], m[8], m[12], m[1], m[2], m[3], m[5], m[6], m[7], m[9], m[10], m[11]):Orthonormalize()
		A[b] = cf
		local p = self.rigParent[b]
		self.rigBones[b].Transform = self.boneCFInv[b] * (p == 0 and cf or A[p]:ToObjectSpace(cf))
	end
end

function ExactAnimator:_applySkin(skin)
	local SM = self.SM
	local doNormals = self.skinFrame % self.normalsEvery == 0
	self.skinFrame += 1
	for _, s in skin do
		local part, em, vids = s.part, s.em, s.vids
		local pos, bi, bw = part.pos, part.bi, part.bw
		for v = 1, part.nV do
			local x, y, z = pos[3 * v - 2], pos[3 * v - 1], pos[3 * v]
			local ox, oy, oz = 0, 0, 0
			local k = 4 * v - 4
			for j = 1, 4 do
				local w = bw[k + j]
				if w > 0 then
					local o = (bi[k + j] - 1) * 12
					ox += w * (SM[o + 1] * x + SM[o + 2] * y + SM[o + 3] * z + SM[o + 4])
					oy += w * (SM[o + 5] * x + SM[o + 6] * y + SM[o + 7] * z + SM[o + 8])
					oz += w * (SM[o + 9] * x + SM[o + 10] * y + SM[o + 11] * z + SM[o + 12])
				end
			end
			em:SetPosition(vids[v], Vector3.new(ox, oy, oz))
		end
		if doNormals then
			local nrm, nvert, nids = part.nrm, part.nvert, s.nids
			for n = 1, part.nN do
				local k = 4 * nvert[n] - 4
				local x, y, z = nrm[3 * n - 2], nrm[3 * n - 1], nrm[3 * n]
				local ox, oy, oz = 0, 0, 0
				for j = 1, 4 do
					local w = bw[k + j]
					if w > 0 then
						local o = (bi[k + j] - 1) * 12
						ox += w * (SM[o + 1] * x + SM[o + 2] * y + SM[o + 3] * z)
						oy += w * (SM[o + 5] * x + SM[o + 6] * y + SM[o + 7] * z)
						oz += w * (SM[o + 9] * x + SM[o + 10] * y + SM[o + 11] * z)
					end
				end
				local len = math.sqrt(ox * ox + oy * oy + oz * oz)
				if len > 1e-9 then em:SetNormal(nids[n], Vector3.new(ox / len, oy / len, oz / len)) end
			end
		end
	end
end

function ExactAnimator:_setMode(mode: string)
	if mode == self.mode then return end
	self.mode = mode
	local useSkin = mode == "skin"
	if type(self.skin) ~= "table" then return end
	for _, s in self.skin do
		s.mp.Transparency = useSkin and 0 or 1
		if s.rigPart then s.rigPart.Transparency = useSkin and 1 or (self.rigTransparency[s.rigPart] or 0) end
	end
end

function ExactAnimator:_apply()
	local root = self.rigRoot
	if not root or not root.Parent then return end
	self:_applyBones()
	local useSkin = false
	if self.skinEnabled and self:_scaleError() > self.skinTolerance then
		local cam = workspace.CurrentCamera
		useSkin = cam == nil or (cam.CFrame.Position - root.Position).Magnitude <= self.lodDistance
	end
	if useSkin and type(self.skin) == "table" then
		self:_applySkin(self.skin)
		self:_setMode("skin")
	else
		if useSkin and self.skin == nil then task.spawn(self._buildSkin, self) end
		self:_setMode("bones")
	end
end

function ExactAnimator:Step(dt: number)
	self.clock += dt
	local active = self.active
	for i = #active, 1, -1 do
		local st = active[i]
		if st.weight ~= st.target then
			if st.fadeSpeed == HUGE then
				st.weight = st.target
			elseif st.weight < st.target then
				st.weight = math.min(st.target, st.weight + st.fadeSpeed * dt)
			else
				st.weight = math.max(st.target, st.weight - st.fadeSpeed * dt)
			end
		end
		if st.target <= 0 and st.weight <= 0 then
			self:_stop(st)
		else
			local prev = st.time
			st.time = prev + dt * st.speed
			self:_queueEvents(st, prev)
		end
	end
	if self.faceRevertAt > 0 and self.clock >= self.faceRevertAt then
		self.faceRevertAt = 0
		self:SetFace(self.faceDefault)
	end
	if #active > 0 and self:_evaluate() then
		local rn = self.rootNode
		if rn then
			local y = self.LT[3 * rn - 1]
			if self.rootPrevY and math.abs(y) >= 0.1 * self.pack.studs then
				self.rootForward += self.rootPrevY - y
			end
			self.rootPrevY = y
		end
		if not self.headless then self:_apply() end
	end
	for i = #active, 1, -1 do
		if active[i].ended then self:_stop(active[i]) end
	end
	if #self.pending > 0 then
		local pending = self.pending
		self.pending = {}
		for _, p in pending do
			local name, e = p[1], p[2]
			if e.fn == "OnFaceAnimTag" then self:_faceTag(e.data) end
			self.Event:Fire(e.fn, e.data, name, e)
		end
	end
end

-- sample one clip at time t (no blending) into self.SM; used by SelfTest and tools
function ExactAnimator:PoseAt(name: string, t: number)
	local st = { clip = self.pack.clips[name], length = self.pack.clips[name].duration, time = t,
		wrapMode = WrapMode.ClampForever, cursors = {} }
	self:_sample(st, self.LT, self.LQ, self.LS)
	self:_compose()
	if not self.headless then self:_applyBones() end
	return self.SM
end

-- driver ----------------------------------------------------------------------------------------------
local running = {}
local conn
function ExactAnimator:Start()
	running[self] = true
	if not conn then
		local ev = RunService:IsClient() and (RunService.PreRender or RunService.RenderStepped) or RunService.Heartbeat
		conn = ev:Connect(function(dt)
			for a in running do
				local ok, err = pcall(a.Step, a, dt)
				if not ok then
					running[a] = nil
					warn("[SPSO] animator stopped: " .. tostring(err))
				end
			end
		end)
	end
end

function ExactAnimator:Destroy()
	running[self] = nil
	if type(self.skin) == "table" then
		for _, s in self.skin do
			s.mp:Destroy()
			if s.rigPart then s.rigPart.Transparency = self.rigTransparency[s.rigPart] or 0 end
		end
	end
	self.skin = false
	self.Event._fns = {}
end

-- proves the runtime reproduces the original curves: pack self-tests (off-grid times included) and a
-- signature of every clip, computed offline with the reference evaluator
function ExactAnimator.SelfTest(pack)
	local a = ExactAnimator.new(pack, nil, { headless = true })
	local NB = #pack.bones
	local maxS, maxSig = 0, 0
	for _, t in pack.tests do
		local SM = a:PoseAt(pack.clipList[t.clip].name, t.time)
		for k = 1, NB * 12 do
			local e = math.abs(SM[k] - t.S[k])
			if e > maxS then maxS = e end
		end
	end
	for _, s in pack.sigs do
		local SM = a:PoseAt(pack.clipList[s.clip].name, s.time)
		local sig = 0
		for b = 1, NB do
			for ij = 1, 12 do sig += SM[(b - 1) * 12 + ij] * b * ij end
		end
		local e = math.abs(sig - s.sig) / math.max(1, math.abs(s.sig))
		if e > maxSig then maxSig = e end
	end
	return { maxMatrixError = maxS, maxSignatureError = maxSig, tests = #pack.tests, clips = #pack.sigs }
end

return ExactAnimator
