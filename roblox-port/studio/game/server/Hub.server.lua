-- SPSO social zones (hub), after the original game's social space: players arrive in a zone with their hero and
--   * collect fractals and hero tokens at the zone's original spawn points (they come back after a while)
--   * meet civilians walking the original NPC paths and pigeons that take off when a hero runs at them
--   * poke the interactive props (hydrants, mailboxes, bins...) to make them jiggle and drop stars
--   * use doors (pairs teleport), the game launchers (mission -> the brawler, zones -> travel) and shops (soon)
-- Zone data: HubData (tools/convert_hub.py); geometry and props are built by setup/02_hub.
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local ServerStorage = game:GetService("ServerStorage")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local Net = require(Game:WaitForChild("Net"))
local HubData = Config.HubData
if not HubData or Config.Mode ~= "Hub" then return end
local H = Config.Hub
local HubRemote = Net.event("Hub")
local hubRoot = workspace:WaitForChild("SPSO_Hub", 30)
local now = os.clock

local function cfOf(t)
	return CFrame.new(t[1], t[2], t[3], t[4], t[5], t[6], t[7], t[8], t[9], t[10], t[11], t[12])
end
local function v3(t) return Vector3.new(t[1], t[2], t[3]) end
local function zoneOf(player: Player): string? return player:GetAttribute("SPSO_Zone") end
local function heroesIn(zone: string)
	local out = {}
	for _, p in Players:GetPlayers() do
		local hrp = p.Character and p.Character:FindFirstChild("HumanoidRootPart")
		if zoneOf(p) == zone and hrp then table.insert(out, { player = p, hrp = hrp }) end
	end
	return out
end
local function notify(player: Player, kind: string, data) HubRemote:FireClient(player, kind, data or {}) end

-- arrival: zone spawn points (the brawler uses its own) -------------------------------------------------------------
_G.SPSO_SpawnCF = function(player: Player): CFrame?
	local z = HubData.Zones[zoneOf(player) or ""]
	if not z or #z.spawns == 0 then return nil end
	return cfOf(z.spawns[math.random(#z.spawns)]) + Vector3.new(0, 3.5, 0)
end
local function counters(p: Player)
	for _, k in { "Fractals", "Tokens", "Stars" } do
		if p:GetAttribute("SPSO_" .. k) == nil then p:SetAttribute("SPSO_" .. k, 0) end
	end
	local ls = p:FindFirstChild("leaderstats") or Instance.new("Folder")
	ls.Name = "leaderstats"
	for _, k in { "Fractals", "Tokens" } do
		local v = ls:FindFirstChild(k) or Instance.new("IntValue")
		v.Name = k
		v.Value = p:GetAttribute("SPSO_" .. k)
		v.Parent = ls
	end
	ls.Parent = p
end
local function add(p: Player, k: string, n: number)
	p:SetAttribute("SPSO_" .. k, (p:GetAttribute("SPSO_" .. k) or 0) + n)
	local v = p:FindFirstChild("leaderstats") and p.leaderstats:FindFirstChild(k)
	if v then v.Value = p:GetAttribute("SPSO_" .. k) end
end
local function onPlayer(p: Player)
	if not zoneOf(p) then p:SetAttribute("SPSO_Zone", Config.StartZone) end
	counters(p)
end
Players.PlayerAdded:Connect(onPlayer)
for _, p in Players:GetPlayers() do task.spawn(onPlayer, p) end

local function travel(player: Player, zone: string)
	if zone ~= "Brawler" and not HubData.Zones[zone] then return end
	player:SetAttribute("SPSO_Zone", zone)
	if _G.SPSO_SpawnHero and player:GetAttribute("SPSO_Hero") then _G.SPSO_SpawnHero(player) end
	notify(player, "zone", { zone = zone })
end
_G.SPSO_Travel = travel

-- collectibles: fractals (crystals) and hero tokens (coins) -------------------------------------------------------
local collectibles = {}
local function collectible(zf: Instance, kind: string, pos: Vector3, respawn: number)
	local p = Instance.new("Part")
	p.Name = kind
	p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, false, false, false
	p.CastShadow = false
	p.Material = Enum.Material.Neon
	if kind == "Fractal" then
		p.Size = Vector3.new(1.3, 2.2, 1.3)
		p.Color = Color3.fromRGB(176, 104, 255)
	else
		p.Shape = Enum.PartType.Cylinder
		p.Size = Vector3.new(0.35, 2.2, 2.2)
		p.Color = Color3.fromRGB(255, 205, 60)
	end
	p.CFrame = CFrame.new(pos + Vector3.new(0, 2.2, 0))
	local light = Instance.new("PointLight")
	light.Color, light.Range, light.Brightness = p.Color, 8, 1.2
	light.Parent = p
	CollectionService:AddTag(p, "SPSO_Collectible")
	p.Parent = zf
	table.insert(collectibles, { part = p, kind = kind, zone = zf.Name, respawn = respawn, back = 0 })
end

-- civilians and pigeons -------------------------------------------------------------------------------------------------
local chars = ServerStorage:WaitForChild("SPSO"):WaitForChild("Characters")
local seq = 0
local function action(model: Model, clip: string)
	seq += 1
	model:SetAttribute("SPSO_Action", string.format("%s|%.4f|0.150|%d", clip, workspace:GetServerTimeNow(), seq))
end
local function spawnModel(name: string, cf: CFrame, parent: Instance): Model?
	local tpl = chars:FindFirstChild("Hero_" .. name)
	if not tpl then return nil end
	local m = tpl:Clone()
	m.Name = name
	m:SetAttribute("SPSO_Hero", name)
	m:SetAttribute("SPSO_Team", "Neutral")
	m:PivotTo(cf)
	m.Parent = parent
	CollectionService:AddTag(m, "SPSO_Fighter")
	return m
end

local civilians, pigeons = {}, {}
local function startCivilians(zoneName: string, z, zf: Instance)
	local names = {}
	for _, c in z.npcs do table.insert(names, HubData.Civilians[c.char] or "CivilianMale1") end
	for i, path in z.npcPaths do
		if #path < 2 then continue end
		for k = 1, 2 do -- the original's random-gender spawns: two walkers per path
			local name = names[((i - 1) * 2 + k - 1) % math.max(#names, 1) + 1] or "CivilianMale1"
			local start = math.random(#path)
			local m = spawnModel(name, CFrame.new(v3(path[start]) + Vector3.new(0, 3.5, 0)), zf)
			if not m then continue end
			m:SetAttribute("SPSO_Walk", true)
			local hum = m:FindFirstChildOfClass("Humanoid")
			hum.WalkSpeed = H.npcWalkSpeed
			hum.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
			pcall(function() m.HumanoidRootPart:SetNetworkOwner(nil) end)
			table.insert(civilians, { model = m, hum = hum, path = path, node = start, dir = k == 1 and 1 or -1, wait = 0 })
		end
	end
end
local function walkCivilians()
	for _, c in civilians do
		local hrp = c.model:FindFirstChild("HumanoidRootPart")
		if not hrp or not c.model.Parent then continue end
		if c.wait > now() then continue end
		local target = v3(c.path[c.node])
		if (hrp.Position * Vector3.new(1, 0, 1) - target * Vector3.new(1, 0, 1)).Magnitude < 3 then
			local nxt = c.node + c.dir
			if nxt < 1 or nxt > #c.path then
				c.dir = -c.dir
				nxt = c.node + c.dir
				if math.random() < 0.5 then -- a pause at the end of the path, sometimes a greeting
					c.wait = now() + 2 + math.random() * 3
					if math.random() < 0.4 then action(c.model, "emote_greet") end
				end
			end
			c.node = math.clamp(nxt, 1, #c.path)
			target = v3(c.path[c.node])
		end
		c.hum:MoveTo(target)
	end
end

local function startPigeons(zoneName: string, z, zf: Instance)
	for _, pos in z.pigeons do
		local cf = CFrame.new(v3(pos) + Vector3.new(0, 1.5, 0)) * CFrame.Angles(0, math.random() * math.pi * 2, 0)
		local m = spawnModel("Pigeon", cf, zf)
		if m then
			m.HumanoidRootPart.Anchored = true
			local hum = m:FindFirstChildOfClass("Humanoid")
			if hum then hum.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None end
			table.insert(pigeons, { model = m, home = cf, zone = zoneName, state = "idle", t = 0 })
		end
	end
end
local function stepPigeons(dt: number)
	for _, pg in pigeons do
		local hrp = pg.model:FindFirstChild("HumanoidRootPart")
		if not hrp then continue end
		if pg.state == "idle" then
			for _, h in heroesIn(pg.zone) do
				if (h.hrp.Position - hrp.Position).Magnitude < H.pigeonScare then
					pg.state, pg.t = "fly", 0
					local away = (hrp.Position - h.hrp.Position) * Vector3.new(1, 0, 1)
					pg.vel = (away.Magnitude > 0.1 and away.Unit or Vector3.xAxis) * 22 + Vector3.new(0, 18, 0)
					action(pg.model, "movement_run_sidekick")
					break
				end
			end
		elseif pg.state == "fly" then
			pg.t += dt
			local p = hrp.Position + pg.vel * dt
			hrp.CFrame = CFrame.lookAt(p, p + pg.vel * Vector3.new(1, 0, 1) + Vector3.new(0, 0.01, 0))
			if pg.t > 3.5 then
				pg.state, pg.t = "gone", 0
				hrp.CFrame = pg.home + Vector3.new(0, -500, 0)
			end
		elseif pg.state == "gone" then
			pg.t += dt
			if pg.t > H.pigeonRespawn then
				pg.state = "idle"
				hrp.CFrame = pg.home
				pg.model:SetAttribute("SPSO_Action", string.format("none|%.4f|0.2|%d", workspace:GetServerTimeNow(), seq))
			end
		end
	end
end

-- props: poke to jiggle (and maybe a star), doors, launchers, shops ---------------------------------------------------
local function prompt(parent: Instance, text: string, object: string, dist: number?)
	local pp = Instance.new("ProximityPrompt")
	pp.ActionText, pp.ObjectText = text, object
	pp.MaxActivationDistance = dist or 10
	pp.RequiresLineOfSight = false
	pp.Parent = parent
	return pp
end
local function anchor(zf: Instance, pos: Vector3, name: string): BasePart
	local a = Instance.new("Part")
	a.Name = name
	a.Anchored, a.CanCollide, a.CanQuery, a.CanTouch = true, false, false, false
	a.Transparency, a.Size = 1, Vector3.one
	a.Position = pos
	a.Parent = zf
	return a
end
local jiggling = {}
local function jiggle(m: Model, player: Player)
	if jiggling[m] and now() < jiggling[m] then return end
	jiggling[m] = now() + H.jiggleCooldown
	local base = m:GetPivot()
	local t0 = now()
	local conn
	conn = RunService.Heartbeat:Connect(function()
		local t = now() - t0
		if t > 0.7 or not m.Parent then
			conn:Disconnect()
			m:PivotTo(base)
			return
		end
		local a = math.sin(t * 38) * 0.12 * (1 - t / 0.7)
		m:PivotTo(base * CFrame.Angles(a, 0, a * 0.6))
	end)
	if math.random() < H.starChance then
		add(player, "Stars", 1)
		notify(player, "collect", { kind = "Star", pos = base.Position + Vector3.new(0, 4, 0) })
	end
end

local function setupZone(zoneName: string, z)
	local zf = hubRoot and hubRoot:FindFirstChild(zoneName)
	if not zf then
		warn("[SPSO] hub zone not built: " .. zoneName)
		return
	end
	local live = zf:FindFirstChild("Live") or Instance.new("Folder")
	live.Name = "Live"
	live:ClearAllChildren()
	live.Parent = zf
	for _, f in z.fractals do collectible(live, "Fractal", v3(f.pos), H.fractalRespawn) end
	for _, t in z.tokens do collectible(live, "Token", v3(t.pos), H.tokenRespawn) end
	startCivilians(zoneName, z, live)
	startPigeons(zoneName, z, live)
	local props = zf:FindFirstChild("Props")
	for _, m in props and props:GetChildren() or {} do
		if m:IsA("Model") and m:GetAttribute("Kind") == "PokeAndJiggle" and m.PrimaryPart then
			local cd = Instance.new("ClickDetector")
			cd.MaxActivationDistance = 40
			cd.Parent = m.PrimaryPart
			cd.MouseClick:Connect(function(player)
				if zoneOf(player) == zoneName then jiggle(m, player) end
			end)
		end
	end
	-- doors: pairs lead to each other
	local byName = {}
	for _, d in z.doors do byName[d.name] = d end
	for _, d in z.doors do
		local ex = d.exit and byName[d.exit]
		if ex then
			local a = anchor(live, cfOf(d.cf).Position + Vector3.new(0, 3, 0), "Door")
			prompt(a, "Enter", "Door", 8).Triggered:Connect(function(player)
				local char = player.Character
				if char and zoneOf(player) == zoneName then char:PivotTo(cfOf(ex.cf) + Vector3.new(0, 3.5, 0)) end
			end)
		end
	end
	for _, s in z.shops do
		local a = anchor(live, v3(s.pos) + Vector3.new(0, 3, 0), "Shop")
		prompt(a, "Browse", string.upper(s.kind), 8).Triggered:Connect(function(player)
			notify(player, "message", { text = "The " .. s.kind .. " is closed for now: come back soon!" })
		end)
	end
	for _, l in z.launchers do
		local a = anchor(live, v3(l.pos) + Vector3.new(0, 3, 0), "Launcher")
		local text = ({ mission = "Start Mission", zones = "Travel", cardgame = "Card Game", hq = "Headquarters" })[l.kind] or "Use"
		prompt(a, text, "", 12).Triggered:Connect(function(player)
			if zoneOf(player) ~= zoneName then return end
			if l.kind == "mission" then
				travel(player, "Brawler")
			elseif l.kind == "zones" then
				notify(player, "zones", {})
			else
				notify(player, "message", { text = "Coming soon!" })
			end
		end)
	end
end

HubRemote.OnServerEvent:Connect(function(player, kind, data)
	if kind == "travel" and type(data) == "table" and type(data.zone) == "string" then
		local f = player.Character
		if f and f:GetAttribute("SPSO_Lock") then return end
		travel(player, data.zone)
	end
end)

for zoneName, z in HubData.Zones do task.spawn(setupZone, zoneName, z) end

local lastCollect, lastWalk = 0, 0
RunService.Heartbeat:Connect(function(dt)
	stepPigeons(dt)
	local t = now()
	if t - lastWalk > 0.5 then
		lastWalk = t
		walkCivilians()
	end
	if t - lastCollect < 0.15 then return end
	lastCollect = t
	for _, c in collectibles do
		if c.back > 0 then
			if t >= c.back then
				c.back = 0
				c.part.Transparency = 0
				c.part.PointLight.Enabled = true
			end
			continue
		end
		for _, h in heroesIn(c.zone) do
			if (h.hrp.Position - c.part.Position).Magnitude < H.collectRadius then
				c.back = t + c.respawn
				c.part.Transparency = 1
				c.part.PointLight.Enabled = false
				add(h.player, c.kind == "Fractal" and "Fractals" or "Tokens", 1)
				notify(h.player, "collect", { kind = c.kind, pos = c.part.Position })
				break
			end
		end
	end
end)
