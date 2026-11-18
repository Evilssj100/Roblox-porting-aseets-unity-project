-- SPSO world setup (Studio, Edit mode; idempotent):
--   require(game.ServerStorage.SPSO.Setup["01_world"])()
-- * archives the template baseplate / spawn and old test objects (ServerStorage.SPSO_Archive, nothing deleted)
-- * builds the playable character templates from the uploaded El Rugido model:
--     ServerStorage.SPSO.Characters.Hero_ElRugido / Enemy_Luchador, StarterPlayer.StarterCharacter
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

	-- hero source model (the uploaded El Rugido asset)
	local source = folder(spso, "Source")
	local import = workspace:FindFirstChild("ElRugido_Import") or source:FindFirstChild("ElRugido_Import")
	assert(import, "El Rugido model not found (workspace.ElRugido_Import)")
	import.Parent = source
	local rigSrc = import:FindFirstChild("ElRugido")
	assert(rigSrc and rigSrc:FindFirstChild("RootPart"), "ElRugido_Import.ElRugido.RootPart missing")

	-- playable character: Humanoid + HumanoidRootPart driving the skinned rig (animated by script)
	local HIP, HRP_SIZE = 2.0, Vector3.new(3, 2.6, 2)
	local function buildCharacter(name: string): Model
		local char = Instance.new("Model")
		char.Name = name
		local rig = rigSrc:Clone()
		for _, c in rig:GetChildren() do
			if c:IsA("AnimationController") then
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
	for _, n in { "Hero_ElRugido", "Enemy_Luchador" } do
		local old = chars:FindFirstChild(n)
		if old then old:Destroy() end
		buildCharacter(n).Parent = chars
	end
	local sc = StarterPlayer:FindFirstChild("StarterCharacter")
	if sc then sc:Destroy() end
	local starter = buildCharacter("StarterCharacter")
	starter.Parent = StarterPlayer
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
		for _, p in arena:GetDescendants() do
			if p:IsA("BasePart") then
				p.Anchored = true
				if string.find(p.Name, "Collision") then
					p.Transparency = 1
					p.CanCollide, p.CanQuery, p.CanTouch = true, true, false
					if p:IsA("MeshPart") then
						pcall(function() p.CollisionFidelity = Enum.CollisionFidelity.PreciseConvexDecomposition end)
					end
				elseif p.Name ~= "SafetyFloor" then
					p.CanCollide, p.CanQuery, p.CanTouch = false, false, false
					p.CastShadow = false
					if string.find(p.Name, "Glass") then p.Transparency = 0.55 end
				end
			end
		end
		if not arena:FindFirstChild("SafetyFloor") then
			local sf = Instance.new("Part")
			sf.Name = "SafetyFloor"
			sf.Shape = Enum.PartType.Cylinder
			sf.Size = Vector3.new(2, 104, 104)
			sf.CFrame = CFrame.new(0, -1.4, 0) * CFrame.Angles(0, 0, math.rad(90))
			sf.Transparency = 1
			sf.Anchored, sf.CanCollide = true, true
			sf.Parent = arena
		end
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
	StarterPlayer.CharacterWalkSpeed = 24
	StarterPlayer.CharacterUseJumpPower = true
	StarterPlayer.CharacterJumpPower = 62
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
