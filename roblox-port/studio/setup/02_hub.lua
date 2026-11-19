-- Setup step: builds the social zones (HubData, tools/convert_hub.py) into workspace.SPSO_Hub, in edit mode:
--   * inserts each zone's geometry files and merged props (Assets.Hub) into ServerStorage.SPSO.HubSource
--   * places every part at the zone's world offset (parts arrive at their bounding-box centres: the zone origin
--     is recovered from any part listed in HubData), Neon glow parts, invisible collision chunks with precise
--     convex decomposition, the zone's box colliders, the replacement signs
--   * props: one template per model, placed at every instance (uniform scale), their own boxes and wedges
-- Idempotent: a zone is rebuilt only when its HubData signature changes.
return function()
	local InsertService = game:GetService("InsertService")
	local ReplicatedStorage = game:GetService("ReplicatedStorage")
	local ServerStorage = game:GetService("ServerStorage")
	local Game = ReplicatedStorage:WaitForChild("SPSO"):WaitForChild("Game")
	local Assets = require(Game:WaitForChild("Assets"):Clone())
	local HubData = require(Game:WaitForChild("HubData"):Clone())
	local log = {}

	local function folder(parent: Instance, name: string): Instance
		local f = parent:FindFirstChild(name)
		if not f then
			f = Instance.new("Folder")
			f.Name = name
			f.Parent = parent
		end
		return f
	end
	local spso = folder(ServerStorage, "SPSO")
	local src = folder(spso, "HubSource")
	local hubRoot = folder(workspace, "SPSO_Hub")

	local function cfOf(t)
		return CFrame.new(t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9], t[10], t[11], t[12])
	end
	local function insert(key: string)
		local m = src:FindFirstChild(key)
		if m then return m end
		local id = Assets.Hub[key]
		if not id then
			table.insert(log, "no asset id for " .. key)
			return nil
		end
		local ok, res = pcall(InsertService.LoadAsset, InsertService, id)
		if not ok then
			table.insert(log, "insert failed " .. key .. ": " .. tostring(res))
			return nil
		end
		res.Name = key
		res.Parent = src
		table.insert(log, "inserted " .. key)
		return res
	end
	local function look(p: BasePart, info)
		p.Anchored, p.CanCollide, p.CanTouch = true, false, false
		p.CanQuery = true
		p.CastShadow = info == nil or info.kind ~= "glow"
		p.Material = Enum.Material.SmoothPlastic
		if info and info.kind == "glow" then
			p.Material = Enum.Material.Neon
			p.Color = Color3.new(info.color[1], info.color[2], info.color[3])
			if p:IsA("MeshPart") then p.TextureID = "" end
		elseif info and info.kind == "color" then
			p.Color = Color3.new(info.color[1], info.color[2], info.color[3])
		else
			p.Color = Color3.new(1, 1, 1)
		end
		if info and info.alpha then p.Transparency = 0.02 end
	end
	local THICK = 1.2
	local function wedge(parent, cf, size)
		local w = Instance.new("WedgePart")
		w.Anchored, w.CanCollide, w.CanQuery, w.CanTouch = true, true, true, false
		w.Transparency, w.CastShadow = 1, false
		w.Size, w.CFrame = size, cf
		w.Parent = parent
	end
	local function triangle(parent, a: Vector3, b: Vector3, c: Vector3)
		local n = (b - a):Cross(c - a)
		if n.Magnitude < 1e-4 then return end
		local back = -n.Unit * (THICK / 2)
		local ab, ac, bc = b - a, c - a, c - b
		local abd, acd, bcd = ab:Dot(ab), ac:Dot(ac), bc:Dot(bc)
		if abd > acd and abd > bcd then c, a = a, c elseif acd > bcd and acd > abd then a, b = b, a end
		ab, ac, bc = b - a, c - a, c - b
		local right = ac:Cross(ab)
		if right.Magnitude < 1e-6 or bc.Magnitude < 1e-6 then return end
		right = right.Unit
		local up, fwd = bc:Cross(right).Unit, bc.Unit
		local h = math.abs(ab:Dot(up))
		if h < 0.01 then return end
		local d1, d2 = math.abs(ab:Dot(fwd)), math.abs(ac:Dot(fwd))
		if d1 > 0.01 then wedge(parent, CFrame.fromMatrix((a + b) / 2 + back, right, up, fwd), Vector3.new(THICK, h, d1)) end
		if d2 > 0.01 then wedge(parent, CFrame.fromMatrix((a + c) / 2 + back, -right, up, -fwd), Vector3.new(THICK, h, d2)) end
	end
	local function box(parent, b, name)
		local p = Instance.new("Part")
		p.Name = name or "Box"
		p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, true, true, false
		p.Transparency, p.CastShadow = 1, false
		p.Size = Vector3.new(math.max(b.size[1], 0.05), math.max(b.size[2], 0.05), math.max(b.size[3], 0.05))
		p.CFrame = cfOf(b.cf)
		p.Parent = parent
		return p
	end

	-- prop templates: the merged props file keeps every model's parts as "<Model>__<n>"
	local templates = {}
	local function propTemplates(key: string)
		if templates[key] then return templates[key] end
		local m = insert(key)
		local out = {}
		if m then
			local origin
			for _, p in m:GetDescendants() do
				if p:IsA("BasePart") then
					local model = string.match(p.Name, "^(.-)__%d+$")
					local info = model and HubData.Props[model] and HubData.Props[model].parts[p.Name]
					if info then
						origin = origin or (p.Position - Vector3.new(info.center[1], info.center[2], info.center[3]))
						out[model] = out[model] or {}
						table.insert(out[model], p)
					end
				end
			end
			out._origin = origin
		end
		templates[key] = out
		return out
	end

	for zoneName, z in HubData.Zones do
		local sig = #z.geometry.files .. ":" .. #z.props .. ":" .. #z.geometry.collision .. ":" .. tostring(z.offset[1])
		local zf = hubRoot:FindFirstChild(zoneName)
		if zf and zf:GetAttribute("Signature") == sig then
			table.insert(log, zoneName .. " up to date")
			continue
		end
		if zf then zf:Destroy() end
		zf = Instance.new("Model")
		zf.Name = zoneName
		local geo, col, propsF = folder(zf, "Geometry"), folder(zf, "Collision"), folder(zf, "Props")
		local off = Vector3.new(z.offset[1], z.offset[2], z.offset[3])
		local placed, missing = 0, 0
		for _, file in z.geometry.files do
			local m = insert((string.gsub(file, "%.fbx$", "")))
			if not m then
				missing += 1
				continue
			end
			local copy = m:Clone()
			local origin
			for _, p in copy:GetDescendants() do
				if p:IsA("BasePart") then
					local info = z.geometry.parts[p.Name]
					if info then
						origin = p.Position - Vector3.new(info.center[1], info.center[2], info.center[3])
						break
					end
				end
			end
			if not origin then -- a file of collision chunks only: use the first chunk's recorded centre
				origin = Vector3.zero
				table.insert(log, file .. ": no reference part, origin assumed")
			end
			for _, p in copy:GetDescendants() do
				if p:IsA("BasePart") then
					p.CFrame = CFrame.new(off - origin) * p.CFrame
					if table.find(z.geometry.collision, p.Name) then
						p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, true, true, false
						p.Transparency, p.CastShadow = 1, false
						pcall(function() p.CollisionFidelity = Enum.CollisionFidelity.PreciseConvexDecomposition end)
						if p:IsA("MeshPart") then p.TextureID = "" end
						p.Parent = col
					else
						look(p, z.geometry.parts[p.Name])
						p.Parent = geo
					end
					placed += 1
				end
			end
			copy:Destroy()
		end
		for _, b in z.geometry.boxes do box(col, b, "Box") end
		-- replacement signs (the original lettering is a licensed name)
		for i, s in z.signs do
			local p = Instance.new("Part")
			p.Name = "Sign_" .. i
			p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, false, false, false
			p.Size = Vector3.new(s.size[1], s.size[2], 0.2)
			p.CFrame = cfOf(s.cf) * CFrame.new(0, 0, -0.35)
			p.Color, p.Material = Color3.fromRGB(46, 44, 40), Enum.Material.SmoothPlastic
			local g = Instance.new("SurfaceGui")
			g.Face = Enum.NormalId.Front
			g.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
			g.PixelsPerStud = 40
			g.LightInfluence = 0.3
			g.Parent = p
			local t = Instance.new("TextLabel")
			t.Size = UDim2.fromScale(1, 1)
			t.BackgroundTransparency = 1
			t.Text = s.text
			t.TextScaled = true
			t.Font = Enum.Font.Merriweather
			t.TextColor3 = Color3.fromRGB(236, 196, 74)
			t.TextStrokeColor3 = Color3.fromRGB(90, 62, 10)
			t.TextStrokeTransparency = 0.2
			t.Parent = g
			p.Parent = geo
		end
		-- props
		local tpl = propTemplates(zoneName .. "_Props")
		local o = tpl._origin and CFrame.new(tpl._origin) or CFrame.new()
		for i, inst in z.props do
			local parts = tpl[inst.model]
			local data = HubData.Props[inst.model]
			if not parts or not data then
				missing += 1
				continue
			end
			local m = Instance.new("Model")
			m.Name = inst.name .. "_" .. i
			m:SetAttribute("Prop", inst.model)
			m:SetAttribute("Kind", inst.kind)
			local cf = cfOf(inst.cf)
			for _, tp in parts do
				local p = tp:Clone()
				local rel = o:ToObjectSpace(tp.CFrame)
				p.Size *= inst.scale
				p.CFrame = cf * (rel - rel.Position + rel.Position * inst.scale)
				look(p, data.parts[p.Name])
				p.Parent = m
			end
			for _, b in data.boxes do
				local bp = box(m, { cf = { 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1 }, size = { b.size[1] * inst.scale, b.size[2] * inst.scale, b.size[3] * inst.scale } }, "Collider")
				local lb = cfOf(b.cf)
				bp.CFrame = cf * (lb - lb.Position + lb.Position * inst.scale)
			end
			if #data.collision > 0 and #data.collision <= 300 then
				local mirror = string.sub(inst.model, -2) == "_M"
				for _, t in data.collision do
					local a, b, c = Vector3.new(t[1], t[2], t[3]), Vector3.new(t[4], t[5], t[6]), Vector3.new(t[7], t[8], t[9])
					if mirror then a, b, c = Vector3.new(-a.X, a.Y, a.Z), Vector3.new(-c.X, c.Y, c.Z), Vector3.new(-b.X, b.Y, b.Z) end
					triangle(m, cf * (a * inst.scale), cf * (b * inst.scale), cf * (c * inst.scale))
				end
			end
			if m.PrimaryPart == nil then
				m.PrimaryPart = m:FindFirstChildWhichIsA("BasePart")
			end
			m.Parent = propsF
		end
		zf:SetAttribute("Signature", sig)
		zf:SetAttribute("Offset", off)
		zf.Parent = hubRoot
		table.insert(log, string.format("%s: %d parts, %d props, %d missing", zoneName, placed, #z.props, missing))
	end
	return table.concat(log, "\n")
end
