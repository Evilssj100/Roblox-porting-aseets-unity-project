-- Builds one original brawler stage in the workspace from MissionData (tools/convert_scenario.py):
--   * every tile at its ObjectPlaceholder placement (mirrored placements use the tile's mirrored model),
--     scaled like the original; parts keep the baked lighting textures, glow parts are Neon
--   * collision: the tiles' own collision meshes rebuilt as wedge pairs (precise, no convex filling),
--     the scenario's invisible walls as boxes
--   * static props (laser holders, power-up crates, parked fighter craft) and the laser gate beams
-- Tile and prop models come from ServerStorage.SPSO.Tiles (inserted by setup/02_tiles).
local MissionData = require(script.Parent:WaitForChild("MissionData"))

local StageBuilder = {}
local THICK = 1.5 -- collision wedge thickness (behind the surface)

local function cfOf(t)
	return CFrame.new(t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9], t[10], t[11], t[12])
end
StageBuilder.cf = cfOf

local function wedge(parent, cf, size)
	local w = Instance.new("WedgePart")
	w.Anchored, w.CanCollide, w.CanQuery, w.CanTouch = true, true, true, false
	w.Transparency = 1
	w.CastShadow = false
	w.Size = size
	w.CFrame = cf
	w.Parent = parent
	return w
end

-- triangle (outward winding) -> two wedges, the surface on the triangle, thickness behind it
local function triangle(parent, a: Vector3, b: Vector3, c: Vector3)
	local n = (b - a):Cross(c - a)
	if n.Magnitude < 1e-4 then return end
	local back = -n.Unit * (THICK / 2)
	local ab, ac, bc = b - a, c - a, c - b
	local abd, acd, bcd = ab:Dot(ab), ac:Dot(ac), bc:Dot(bc)
	if abd > acd and abd > bcd then
		c, a = a, c
	elseif acd > bcd and acd > abd then
		a, b = b, a
	end
	ab, ac, bc = b - a, c - a, c - b
	local right = ac:Cross(ab)
	if right.Magnitude < 1e-6 or bc.Magnitude < 1e-6 then return end
	right = right.Unit
	local up = bc:Cross(right).Unit
	local fwd = bc.Unit
	local h = math.abs(ab:Dot(up))
	if h < 0.01 then return end
	local d1, d2 = math.abs(ab:Dot(fwd)), math.abs(ac:Dot(fwd))
	if d1 > 0.01 then
		wedge(parent, CFrame.fromMatrix((a + b) / 2 + back, right, up, fwd), Vector3.new(THICK, h, d1))
	end
	if d2 > 0.01 then
		wedge(parent, CFrame.fromMatrix((a + c) / 2 + back, -right, up, -fwd), Vector3.new(THICK, h, d2))
	end
end

-- one tile / prop model placed like the game's ObjectPlaceholder: world CFrame, uniform scale
function StageBuilder.place(templates: Instance, name: string, cf: CFrame, scale: number, parent: Instance, collisionParent: Instance?)
	local info = MissionData.Tiles[name]
	local tpl = templates:FindFirstChild(name)
	if not info or not tpl then
		warn("[SPSO] stage model missing: " .. name)
		return nil
	end
	local m = tpl:Clone()
	-- the imported parts sit at their bounding-box centres: recover the tile origin from any known part
	local origin
	for _, p in m:GetDescendants() do
		local pi = p:IsA("BasePart") and info.parts[p.Name]
		if pi then
			origin = p.Position - Vector3.new(pi.center[1], pi.center[2], pi.center[3])
			break
		end
	end
	if not origin then
		m:Destroy()
		warn("[SPSO] no known parts in " .. name)
		return nil
	end
	local o = CFrame.new(origin)
	for _, p in m:GetDescendants() do
		if p:IsA("BasePart") then
			local rel = o:ToObjectSpace(p.CFrame)
			p.Size *= scale
			p.CFrame = cf * (rel - rel.Position + rel.Position * scale)
			p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, false, false, false
			p.CastShadow = false
			local pi = info.parts[p.Name]
			if pi and pi.kind == "glow" then
				p.Material = Enum.Material.Neon
				p.Color = Color3.new(pi.color[1], pi.color[2], pi.color[3])
				if p:IsA("MeshPart") then p.TextureID = "" end
			elseif pi and pi.kind == "color" then
				p.Material = Enum.Material.SmoothPlastic
				p.Color = Color3.new(pi.color[1], pi.color[2], pi.color[3])
			else
				p.Material = Enum.Material.SmoothPlastic
				p.Color = Color3.new(1, 1, 1)
			end
			if pi and pi.alpha then p.Transparency = 0.25 end
		end
	end
	m.Name = name
	m.Parent = parent
	if collisionParent and info.collision and #info.collision > 0 then
		local mirror = string.sub(name, -2) == "_M"
		local folder = Instance.new("Folder")
		folder.Name = name
		for _, t in info.collision do
			local a = Vector3.new(t[1], t[2], t[3])
			local b = Vector3.new(t[4], t[5], t[6])
			local c = Vector3.new(t[7], t[8], t[9])
			if mirror then -- collision is stored for the un-mirrored tile
				a, b, c = Vector3.new(-a.X, a.Y, a.Z), Vector3.new(-c.X, c.Y, c.Z), Vector3.new(-b.X, b.Y, b.Z)
			end
			triangle(folder, cf * (a * scale), cf * (b * scale), cf * (c * scale))
		end
		folder.Parent = collisionParent
	end
	return m
end

local function box(parent, b, name: string, transparency: number?)
	local p = Instance.new("Part")
	p.Name = name
	p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, true, true, false
	p.Transparency = transparency or 1
	p.CastShadow = false
	p.Size = Vector3.new(math.max(b.size[1], 0.05), math.max(b.size[2], 0.05), math.max(b.size[3], 0.05))
	p.CFrame = cfOf(b.cf)
	p.Parent = parent
	return p
end

-- the whole stage; returns the folder and the crate models (breakable power-up crates)
function StageBuilder.build(stage, templates: Instance, parent: Instance)
	local folder = Instance.new("Folder")
	folder.Name = "SPSO_Stage"
	local geo = Instance.new("Folder")
	geo.Name = "Geometry"
	geo.Parent = folder
	local col = Instance.new("Folder")
	col.Name = "Collision"
	col.Parent = folder
	for _, t in stage.tiles do
		StageBuilder.place(templates, t.tile, cfOf(t.cf), t.scale, geo, col)
	end
	local crates = {}
	for i, p in stage.props do
		local m = StageBuilder.place(templates, p.model, cfOf(p.cf), p.scale, geo, not p.crate and col or nil)
		if m and p.crate then
			m.Name = "Crate_" .. i
			table.insert(crates, m)
		end
	end
	for _, w in stage.walls do
		box(col, w, "Wall")
	end
	local lasers = Instance.new("Folder")
	lasers.Name = "Lasers"
	lasers.Parent = geo
	for _, l in stage.lasers do
		local p = Instance.new("Part")
		p.Name = "LaserGate"
		p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, false, false, false
		p.Material = Enum.Material.Neon
		p.Color = Color3.fromRGB(255, 60, 140)
		p.Transparency = 0.35
		p.CastShadow = false
		local dir = Vector3.new(l.dir[1], l.dir[2], l.dir[3]).Unit
		local base = cfOf(l.cf)
		p.Size = Vector3.new(math.max(l.width * 0.5, 0.15), math.max(l.width * 0.5, 0.15), l.length)
		p.CFrame = CFrame.lookAt(base.Position, base.Position + dir)
		p.Parent = lasers
	end
	folder.Parent = parent
	return folder, crates
end

return StageBuilder
