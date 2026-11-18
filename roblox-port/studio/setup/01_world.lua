-- SPSO world setup (Studio, Edit mode; idempotent):
--   require(game.ServerStorage.SPSO.Setup["01_world"])()
-- * archives the template baseplate / spawn and old test objects (ServerStorage.SPSO_Archive, nothing deleted)
-- * inserts every hero's uploaded model and data package (Assets.lua) and builds the character templates
--     ServerStorage.SPSO.Characters.Hero_<Hero> plus select-screen previews in ReplicatedStorage.SPSO.Previews
--     (players spawn as the hero they pick: Players.CharacterAutoLoads is off)
-- * configures the arena (workspace.OrbitalArena from the uploaded model: collision, glass, spawns), or builds
--   a simple placeholder arena with the same layout when the map has not been inserted yet
-- * lighting and player settings
return function(): string
	local ServerStorage = game:GetService("ServerStorage")
	local StarterPlayer = game:GetService("StarterPlayer")
	local Lighting = game:GetService("Lighting")
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
	local archive = folder(ServerStorage, "SPSO_Archive")

	for _, n in { "Baseplate", "SpawnLocation", "ElRugido_ExactSkinTest" } do
		local o = workspace:FindFirstChild(n)
		if o then
			o.Parent = archive
			table.insert(log, "archived " .. n)
		end
	end

	-- hero source models (uploaded FBX assets, Assets.Heroes[H].model) and their data packages
	local ReplicatedStorage = game:GetService("ReplicatedStorage")
	local InsertService = game:GetService("InsertService")
	local Players = game:GetService("Players")
	local Game = ReplicatedStorage:WaitForChild("SPSO"):WaitForChild("Game")
	local Assets = require(Game:WaitForChild("Assets"):Clone())
	local GameData = require(Game:WaitForChild("GameData"):Clone())
	local unpack = require(spso.Tools.Unpack:Clone())
	local source = folder(spso, "Source")
	local legacy = workspace:FindFirstChild("ElRugido_Import")
	if legacy then legacy.Parent = source end
	local heroesFolder = folder(ReplicatedStorage.SPSO, "Heroes")
	for _, hero in GameData.HeroOrder do
		local a = Assets.Heroes[hero] or {}
		if not source:FindFirstChild(hero .. "_Import") and a.model then
			local m = InsertService:LoadAsset(a.model)
			m.Name = hero .. "_Import"
			m.Parent = source
			table.insert(log, "inserted " .. hero)
		end
		local hf = heroesFolder:FindFirstChild(hero)
		local pack = hf and hf:FindFirstChild("Pack")
		if a.package and (not pack or pack:GetAttribute("PackageId") ~= a.package) then
			unpack(a.package)
			heroesFolder:WaitForChild(hero):WaitForChild("Pack"):SetAttribute("PackageId", a.package)
			table.insert(log, "hero data " .. hero)
		end
	end

	-- playable characters: Humanoid + HumanoidRootPart driving the skinned rig (animated by script)
	local HIP, HRP_SIZE = 2.0, Vector3.new(3, 2.6, 2)
	local function buildCharacter(rigSrc: Model, name: string): Model
		local char = Instance.new("Model")
		char.Name = name
		local rig = rigSrc:Clone()
		for _, c in rig:GetChildren() do
			if c:IsA("AnimationController") or c.Name == "InitialPoses" then
				c:Destroy()
			else
				c.Parent = char
			end
		end
		rig:Destroy()
		local root = char:FindFirstChild("RootPart") :: BasePart
		root.CFrame = CFrame.new(0, 0, 0)
		local hrp = Instance.new("Part")
		hrp.Name = "HumanoidRootPart"
		hrp.Size = HRP_SIZE
		hrp.Transparency = 1
		hrp.CanCollide, hrp.Anchored = true, false
		hrp.TopSurface, hrp.BottomSurface = Enum.SurfaceType.Smooth, Enum.SurfaceType.Smooth
		hrp.CFrame = CFrame.new(0, HIP + HRP_SIZE.Y / 2, 0)
		hrp.Parent = char
		for _, p in char:GetDescendants() do
			if p:IsA("BasePart") and p ~= hrp then
				p.Anchored, p.CanCollide, p.CanTouch, p.Massless = false, false, false, true
				p.CanQuery = false
				if p == root then p.Transparency = 1 end
			end
		end
		local m6 = Instance.new("Motor6D")
		m6.Name = "RigRoot"
		m6.Part0, m6.Part1 = hrp, root
		m6.C0 = CFrame.new(0, -(HIP + HRP_SIZE.Y / 2), 0)
		m6.Parent = hrp
		local hum = Instance.new("Humanoid")
		hum.RigType = Enum.HumanoidRigType.R15
		hum.HipHeight = HIP
		hum.BreakJointsOnDeath = false
		hum.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
		hum.HealthDisplayType = Enum.HumanoidHealthDisplayType.AlwaysOff
		hum.Parent = char
		char.PrimaryPart = hrp
		return char
	end
	local chars = folder(spso, "Characters")
	local previews = folder(ReplicatedStorage.SPSO, "Previews")
	for _, n in { "Enemy_Luchador" } do
		local old = chars:FindFirstChild(n)
		if old then old:Destroy() end
	end
	for _, hero in GameData.HeroOrder do
		local import = source:FindFirstChild(hero .. "_Import")
		local rigSrc = import and import:FindFirstChild(hero)
		if rigSrc and rigSrc:FindFirstChild("RootPart") then
			local old = chars:FindFirstChild("Hero_" .. hero)
			if old then old:Destroy() end
			buildCharacter(rigSrc, "Hero_" .. hero).Parent = chars
			-- select-screen preview: the bare rig, posed on the client by its own ExactAnimator
			local pv = previews:FindFirstChild(hero)
			if pv then pv:Destroy() end
			pv = rigSrc:Clone()
			for _, c in pv:GetChildren() do
				if c:IsA("AnimationController") or c.Name == "InitialPoses" then c:Destroy() end
			end
			for _, p in pv:GetDescendants() do
				if p:IsA("BasePart") then p.Anchored = true end
			end
			pv.Name = hero
			pv.Parent = previews
		else
			table.insert(log, "MISSING model for " .. hero)
		end
	end
	local sc = StarterPlayer:FindFirstChild("StarterCharacter")
	if sc then sc.Parent = archive end
	Players.CharacterAutoLoads = false
	table.insert(log, "characters built")

	-- arena
	local arena = workspace:FindFirstChild("OrbitalArena")
	if arena and arena:GetAttribute("Placeholder") and workspace:FindFirstChild("OrbitalArena_Real") then
		arena:Destroy()
		arena = workspace.OrbitalArena_Real
		arena.Name = "OrbitalArena"
	end
	if not arena then
		-- placeholder with the real arena's footprint (floor radius ~49 studs, back wall at -Z)
		arena = Instance.new("Model")
		arena.Name = "OrbitalArena"
		arena:SetAttribute("Placeholder", true)
		local floor = Instance.new("Part")
		floor.Name = "Floor"
		floor.Shape = Enum.PartType.Cylinder
		floor.Size = Vector3.new(2, 100, 100)
		floor.CFrame = CFrame.new(0, -1, 0) * CFrame.Angles(0, 0, math.rad(90))
		floor.Color = Color3.fromRGB(150, 214, 222)
		floor.Material = Enum.Material.SmoothPlastic
		floor.Anchored = true
		floor.Parent = arena
		for i = 0, 31 do
			local a = i / 32 * math.pi * 2
			local w = Instance.new("Part")
			w.Name = "Wall"
			w.Size = Vector3.new(10.4, 26, 2)
			w.CFrame = CFrame.new(math.sin(a) * 51, 12, math.cos(a) * 51) * CFrame.Angles(0, a, 0)
			w.Color = Color3.fromRGB(38, 120, 150)
			w.Material = Enum.Material.SmoothPlastic
			w.Anchored = true
			w.Transparency = (math.cos(a) > 0.5) and 0.85 or 0
			w.Parent = arena
		end
		arena.Parent = workspace
		table.insert(log, "placeholder arena built")
	else
		-- the FBX import puts the back wall (medallion) at +Z; the game expects it at -Z
		local med = arena:FindFirstChild("OrbitalArena_Medallion", true)
		if med and med.Position.Z > 0 then
			for _, p in arena:GetChildren() do
				if p:IsA("MeshPart") then p.CFrame = CFrame.Angles(0, math.pi, 0) * p.CFrame end
			end
		end
		local door = arena:FindFirstChild("OrbitalArena_IrisDoor_Left", true)
		if door then pcall(function() door.DoubleSided = true end) end -- mirrored in the source scene
		for _, p in arena:GetDescendants() do
			if p:IsA("BasePart") and p.Parent and p.Parent.Name ~= "Collision" then
				p.Anchored = true
				p.CanCollide, p.CanQuery, p.CanTouch = false, false, false
				p.CastShadow = false
				if string.find(p.Name, "_Collision") then p.Transparency = 1 end
				if string.find(p.Name, "Glass") then p.Transparency = 0.55 end
			end
		end
		-- collision from primitives: the original collision mesh is a flat floor inside a 12-sided wall
		-- (a convex decomposition of it fills the bowl, so it is only kept as reference)
		local col = arena:FindFirstChild("Collision")
		if col then col:Destroy() end
		col = Instance.new("Folder")
		col.Name = "Collision"
		local function box(name, cf, size)
			local b = Instance.new("Part")
			b.Name, b.CFrame, b.Size = name, cf, size
			b.Transparency, b.Anchored, b.CanCollide, b.CanQuery, b.CanTouch = 1, true, true, true, false
			b.TopSurface, b.BottomSurface = Enum.SurfaceType.Smooth, Enum.SurfaceType.Smooth
			b.Parent = col
		end
		local floorY, wallH = 0, 85
		local floorPart = Instance.new("Part")
		floorPart.Name, floorPart.Shape = "Floor", Enum.PartType.Cylinder
		floorPart.Size = Vector3.new(4, 104, 104)
		floorPart.CFrame = CFrame.new(0, floorY - 2, 0) * CFrame.Angles(0, 0, math.rad(90))
		floorPart.Transparency, floorPart.Anchored, floorPart.CanCollide, floorPart.CanQuery = 1, true, true, true
		floorPart.Parent = col
		local poly = { {49.5, -13.2}, {49.5, 13.3}, {36.3, 36.3}, {13.3, 49.5}, {-13.3, 49.5}, {-36.3, 36.3},
			{-49.5, 13.3}, {-49.5, -13.2}, {-36.3, -36.2}, {-13.3, -49.5}, {13.3, -49.5}, {36.3, -36.2} }
		for i, a in poly do
			local b = poly[i % #poly + 1]
			local pa, pb = Vector3.new(a[1], 0, a[2]), Vector3.new(b[1], 0, b[2])
			local mid, len = (pa + pb) / 2, (pb - pa).Magnitude
			local out = mid.Unit
			local cf = CFrame.lookAt(mid + out * 2 + Vector3.new(0, floorY + wallH / 2, 0), mid + out * 3 + Vector3.new(0, floorY + wallH / 2, 0))
			box("Wall" .. i, cf, Vector3.new(len + 4, wallH, 4))
		end
		col.Parent = arena
		local sf = arena:FindFirstChild("SafetyFloor")
		if sf then sf:Destroy() end
		table.insert(log, "arena configured")
	end
	local spawns = arena:FindFirstChild("Spawns")
	if spawns then spawns:Destroy() end
	spawns = Instance.new("Folder")
	spawns.Name = "Spawns"
	local function marker(name: string, pos: Vector3, face: Vector3)
		local p = Instance.new("Part")
		p.Name = name
		p.Size = Vector3.new(2, 0.2, 2)
		p.CFrame = CFrame.lookAt(pos, pos + face)
		p.Transparency = 1
		p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, false, false, false
		p.Parent = spawns
	end
	for i, x in { -8, 8, -16, 16 } do marker("Player" .. i, Vector3.new(x, 0.2, 30 - math.abs(x) / 4), Vector3.new(0, 0, -1)) end
	local enemyPts = { Vector3.new(-30, 0.2, -26), Vector3.new(30, 0.2, -26), Vector3.new(0, 0.2, -38), Vector3.new(-42, 0.2, 2),
		Vector3.new(42, 0.2, 2), Vector3.new(-18, 0.2, -40), Vector3.new(18, 0.2, -40), Vector3.new(0, 0.2, -18) }
	for i, p in enemyPts do marker(string.format("Enemy%02d", i), p, Vector3.new(0, 0, 1)) end
	spawns.Parent = arena

	-- settings
	workspace.StreamingEnabled = false
	StarterPlayer.LoadCharacterAppearance = false
	StarterPlayer.CharacterUseJumpPower = true
	workspace.Gravity = GameData.Heroes[GameData.HeroOrder[1]].gravity -- the original 20 units/s^2
	Lighting.Brightness = 2
	Lighting.Ambient = Color3.fromRGB(96, 106, 120)
	Lighting.OutdoorAmbient = Color3.fromRGB(128, 138, 150)
	Lighting.ClockTime = 14.5
	Lighting.GlobalShadows = true
	Lighting.EnvironmentDiffuseScale = 0.4
	Lighting.EnvironmentSpecularScale = 0.2
	table.insert(log, "settings applied")
	return table.concat(log, "; ")
end
