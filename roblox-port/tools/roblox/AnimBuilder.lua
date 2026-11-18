--!native
-- SPSO port: build exact native KeyframeSequences for a hero from its per-frame skinning matrices.
--
-- Data (downloaded over HttpService from the roblox-port branch):
--   manifest.json        bones (data order), clips (name, samples, rate, scale deviation, events)
--   clips/<clip>.bin     "SPSOCLP1", u32 T, u32 NB, f32 rate, then T*NB 3x4 row-major skinning matrices
--                        S_b(t) = G·W_b(t)·bind_b^-1·G^-1 in the rig's model space (RootPart at origin)
-- For a clip without bone scaling, each S is rigid, so the bone's animated model-space frame is
--   A_b(t) = S_b(t) * Rest_b      (Rest_b = bone world CFrame relative to RootPart, rest pose)
-- and the Roblox pose is
--   Transform_b(t) = Bone.CFrame^-1 * A_parent(t)^-1 * A_b(t)
-- Keys are dropped only where Roblox's linear interpolation (lerp + slerp) reproduces the
-- dropped samples within posTol studs / angTol radians.
local Http = game:GetService("HttpService")

local M = {}

local function get(base, path)
	return Http:GetAsync(base .. path, true)
end

local function readS(b, off)
	local r0, r1, r2, tx = buffer.readf32(b, off), buffer.readf32(b, off + 4), buffer.readf32(b, off + 8), buffer.readf32(b, off + 12)
	local r4, r5, r6, ty = buffer.readf32(b, off + 16), buffer.readf32(b, off + 20), buffer.readf32(b, off + 24), buffer.readf32(b, off + 28)
	local r8, r9, r10, tz = buffer.readf32(b, off + 32), buffer.readf32(b, off + 36), buffer.readf32(b, off + 40), buffer.readf32(b, off + 44)
	return CFrame.new(tx, ty, tz, r0, r1, r2, r4, r5, r6, r8, r9, r10):Orthonormalize()
end

local function ang(a, b)
	local _, angle = (a.Rotation:Inverse() * b.Rotation):ToAxisAngle()
	return math.abs(angle)
end

local function isIdentity(cf, posTol, angTol)
	return cf.Position.Magnitude <= posTol and ang(cf, CFrame.identity) <= angTol
end

local function reduce(cfs, times, posTol, angTol)
	local n = #cfs
	if n <= 2 then
		local all = {}
		for i = 1, n do all[i] = i end
		return all
	end
	local keep = {1}
	local s, j = 1, 3
	while j <= n do
		-- cap the rotation between kept keys (4 deg) so the result does not depend on whether the
		-- engine interpolates rotations by slerp or nlerp (they differ for wide spans)
		local ok = ang(cfs[s], cfs[j]) <= 0.07
		for m = s + 1, ok and j - 1 or s do
			local a = (times[m] - times[s]) / (times[j] - times[s])
			local pred = cfs[s]:Lerp(cfs[j], a)
			if (pred.Position - cfs[m].Position).Magnitude > posTol or ang(pred, cfs[m]) > angTol then
				ok = false
				break
			end
		end
		if ok then
			j += 1
		else
			table.insert(keep, j - 1)
			s = j - 1
			j = s + 2
		end
	end
	table.insert(keep, n)
	return keep
end

-- Rest frame of a bone in model space (RootPart = origin), from the pure Bone.CFrame chain.
-- (Bone.WorldCFrame includes the ancestors' animated Transforms, so it is not a rest frame.)
function M.restFrame(bone)
	local cf = bone.CFrame
	local p = bone.Parent
	while p and p:IsA("Bone") do
		cf = p.CFrame * cf
		p = p.Parent
	end
	return cf
end

-- rig: Model whose PrimaryPart (RootPart) holds the Bone tree
function M.rigInfo(rig)
	local root = rig.PrimaryPart
	local byName = {}
	for _, d in ipairs(root:GetDescendants()) do
		if d:IsA("Bone") then byName[d.Name] = d end
	end
	return root, byName
end

local LOOPS = {movement_idle = true, movement_run = true, pickup_idle = true, pickup_run = true, sit_idle = true,
	jump_fall_loop = true, jump_run_fall_loop = true, emote_manipulate_loop = true}

local function priority(name)
	if name == "movement_idle" or name == "sit_idle" or name == "pickup_idle" then return Enum.AnimationPriority.Idle end
	if name:match("^movement_") or name == "pickup_run" then return Enum.AnimationPriority.Movement end
	return Enum.AnimationPriority.Action
end

-- Build one clip. Returns the KeyframeSequence (unparented) and stats.
function M.buildClip(base, rig, manifest, clipMeta, posTol, angTol)
	posTol, angTol = posTol or 1e-4, angTol or 1e-4
	local root, byName = M.rigInfo(rig)
	local order = manifest.bones
	local NBd = #order
	local rest, parentName = {}, {}
	for i, name in ipairs(order) do
		local bone = byName[name]
		assert(bone, "rig has no bone " .. name)
		rest[i] = M.restFrame(bone)
		parentName[i] = bone.Parent:IsA("Bone") and bone.Parent.Name or nil
	end
	local idx = {}
	for i, name in ipairs(order) do idx[name] = i end

	local b = buffer.fromstring(get(base, "clips/" .. clipMeta.name .. ".bin"))
	assert(buffer.readstring(b, 0, 8) == "SPSOCLP1", "bad clip file")
	local T, NB, rate = buffer.readu32(b, 8), buffer.readu32(b, 12), buffer.readf32(b, 16)
	assert(NB == NBd, "bone count mismatch")
	local times = table.create(T)
	for k = 1, T do times[k] = (k - 1) / rate end
	if clipMeta.duration and math.abs(times[T] - clipMeta.duration) < 1 / rate then times[T] = clipMeta.duration end

	-- transforms per bone per sample (parents first: bones are stored in hierarchy order)
	local tf = table.create(NBd)
	for i = 1, NBd do tf[i] = table.create(T) end
	for k = 1, T do
		local A = table.create(NBd)
		local base0 = 20 + (k - 1) * NB * 48
		for i = 1, NBd do
			A[i] = readS(b, base0 + (i - 1) * 48) * rest[i]
		end
		for i, name in ipairs(order) do
			local bone = byName[name]
			local Ap = parentName[i] and A[idx[parentName[i]]] or CFrame.identity
			tf[i][k] = bone.CFrame:Inverse() * Ap:Inverse() * A[i]
		end
		if k % 40 == 0 then task.wait() end
	end

	-- per-bone key reduction
	local keys, keyed = {}, {}
	local nKeys = 0
	for i = 1, NBd do
		local allId = true
		for k = 1, T do
			if not isIdentity(tf[i][k], posTol, angTol) then allId = false break end
		end
		if allId then
			keys[i] = {}
		else
			keys[i] = reduce(tf[i], times, posTol, angTol)
		end
		keyed[i] = {}
		for _, k in ipairs(keys[i]) do keyed[i][k] = true end
		nKeys += #keys[i]
	end

	-- union of key samples (+ event samples) -> Keyframes
	local frames = {}
	for i = 1, NBd do for _, k in ipairs(keys[i]) do frames[k] = true end end
	frames[1], frames[T] = true, true
	local events = clipMeta.events or {}
	local eventFrames = {}
	for _, e in ipairs(events) do
		local k = math.clamp(math.floor(e.time * rate + 0.5) + 1, 1, T)
		frames[k] = true
		eventFrames[k] = eventFrames[k] or {}
		table.insert(eventFrames[k], e)
	end
	local list = {}
	for k in pairs(frames) do table.insert(list, k) end
	table.sort(list)

	local children = {}
	for i = 1, NBd do
		local p = parentName[i] or "__root"
		children[p] = children[p] or {}
		table.insert(children[p], i)
	end
	local function subtreeKeyed(i, k)
		if keyed[i][k] then return true end
		for _, c in ipairs(children[order[i]] or {}) do
			if subtreeKeyed(c, k) then return true end
		end
		return false
	end

	local kfs = Instance.new("KeyframeSequence")
	kfs.Name = clipMeta.name
	kfs.Loop = LOOPS[clipMeta.name] == true
	kfs.Priority = priority(clipMeta.name)
	local nPoses = 0
	for n, k in ipairs(list) do
		local kf = Instance.new("Keyframe")
		kf.Time = times[k]
		local rootPose = Instance.new("Pose")
		rootPose.Name = root.Name
		rootPose.Weight = 0
		rootPose.Parent = kf
		local function addPose(i, parentPose)
			if not subtreeKeyed(i, k) then return end
			local pose = Instance.new("Pose")
			pose.Name = order[i]
			-- always the exact sampled value: Roblox does not treat Weight-0 placeholder poses as
			-- "no key" (measured: placeholders add ~0.009 studs / 0.29 deg of error), so a parent pose
			-- that only exists to carry a child's key gets its true value too
			pose.CFrame = tf[i][k]
			pose.Weight = 1
			pose.EasingStyle = Enum.PoseEasingStyle.Linear
			pose.EasingDirection = Enum.PoseEasingDirection.In
			pose.Parent = parentPose
			nPoses += 1
			for _, c in ipairs(children[order[i]] or {}) do addPose(c, pose) end
		end
		for _, i in ipairs(children["__root"] or {}) do addPose(i, rootPose) end
		for _, e in ipairs(eventFrames[k] or {}) do
			local mk = Instance.new("KeyframeMarker")
			mk.Name = e["function"]
			mk.Value = e.data or ""
			mk.Parent = kf
		end
		kf.Parent = kfs
		if n % 25 == 0 then task.wait() end
	end
	kfs:SetAttribute("SourceSamples", T)
	kfs:SetAttribute("SampleRate", rate)
	kfs:SetAttribute("Duration", times[T])
	return kfs, {samples = T, keyframes = #list, keys = nKeys, poses = nPoses}
end

-- Expected model-space bone frames for a clip sample (for verification)
function M.expected(base, rig, manifest, clipName, k)
	local root, byName = M.rigInfo(rig)
	local b = buffer.fromstring(get(base, "clips/" .. clipName .. ".bin"))
	local NB = buffer.readu32(b, 12)
	local out = {}
	for i, name in ipairs(manifest.bones) do
		local rest = M.restFrame(byName[name])
		out[name] = readS(b, 20 + ((k - 1) * NB + (i - 1)) * 48) * rest
	end
	return out
end

return M
