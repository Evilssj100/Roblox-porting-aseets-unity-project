-- SPSO social zones (hub), after the original game's social space: players arrive in a zone with their hero and
--   * find their hero's daily pickups (original activities): 10 fractals, 5 hero tokens and the golden fractal a
--     day per hero, each player seeing their own at seeded spots of the zone's original spawn points
--   * meet civilians walking the original NPC paths and pigeons that take off when a hero runs at them
--   * poke the interactive props (hydrants, mailboxes, bins...) to make them jiggle and drop stars
--   * use doors (pairs teleport), the game launchers (mission -> the brawler, zones -> travel) and the store
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
local assignPickups -- daily pickups, below
local function onPlayer(p: Player)
	if not zoneOf(p) then p:SetAttribute("SPSO_Zone", Config.StartZone) end
	p:GetAttributeChangedSignal("SPSO_Zone"):Connect(function() assignPickups(p) end)
	p:GetAttributeChangedSignal("SPSO_Hero"):Connect(function() assignPickups(p) end)
	p.CharacterAdded:Connect(function() task.defer(assignPickups, p) end)
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

-- pickup models: Hub_Pickups (tools/build_hub_pickups.py: the original fractal shard, an original token coin and
-- star), inserted by setup/02_hub; a copy goes to ReplicatedStorage: each client shows its own pickups
local pickupSrc = ServerStorage:FindFirstChild("SPSO") and ServerStorage.SPSO:FindFirstChild("HubSource")
pickupSrc = pickupSrc and pickupSrc:FindFirstChild("Hub_Pickups")
local pickupTpl = {}
if pickupSrc then
	for _, d in pickupSrc:GetDescendants() do
		local name = d:IsA("MeshPart") and string.match(d.Name, "^(.-)__%d+$")
		if name then pickupTpl[name] = d end
	end
	local rep = Instance.new("Folder")
	rep.Name = "HubPickups"
	for name, t in pickupTpl do
		local c = t:Clone()
		c.Name = name
		c.Parent = rep
	end
	rep.Parent = SPSO
end

-- daily pickups (original SHSFractalsActivity / SHSFeathersActivity / SHSGoldenFractalActivity): for a hero, a
-- zone and a day, a seeded pick of the zone's spawn points the hero can reach gets the fractal indices 1..10 and
-- the token indices 1..5; an index collected anywhere is gone for that hero until tomorrow. The golden fractal
-- shows in one zone a day per hero. Spots for flying or wall-crawling heroes wait until the hub has those moves.
local E = Config.Economy
local PICKUP_LIFT = Vector3.new(0, 2.2, 0)
local PRIMARY = {}
for name, z in HubData.Zones do
	if #z.fractals > 0 then table.insert(PRIMARY, name) end
end
table.sort(PRIMARY, function(a, b) return HubData.Zones[a].order < HubData.Zones[b].order end)
local function hash(s: string): number
	local h = 5381
	for i = 1, #s do h = (h * 33 + string.byte(s, i)) % 2147483647 end
	return h
end
local function reachable(list)
	local out = {}
	for _, s in list do
		if not s.flying and not s.wallcrawl then table.insert(out, s) end
	end
	return out
end
local function pick(rng: Random, list, n: number)
	local pool, out = table.clone(list), {}
	for i = 1, math.min(n, #pool) do out[i] = table.remove(pool, rng:NextInteger(1, #pool)) end
	return out, pool
end
local mine = {} -- player -> { zone, hero, day, list = { { id, kind, index, pos } } }
assignPickups = function(player: Player)
	local zone, hero = zoneOf(player), player:GetAttribute("SPSO_Hero")
	local z = zone and HubData.Zones[zone]
	local eco = _G.SPSO_Economy
	local st = eco and z and hero and eco.dailyState(player, hero)
	if not st then
		mine[player] = nil
		if player.Parent then notify(player, "pickups", { list = {} }) end
		if z and hero and player.Parent then task.delay(1, function() -- the profile is still loading
			if not mine[player] then assignPickups(player) end
		end) end
		return
	end
	local list = {}
	local seed = hash(hero) + st.dayNumber * 7919
	local fr, rest = pick(Random.new(seed + z.order * 104729), reachable(z.fractals), E.dailyFractals)
	for i, s in fr do
		if not st.fractal[i] then table.insert(list, { id = "f" .. i, kind = "Fractal", index = i, pos = v3(s.pos) }) end
	end
	local gzone = #PRIMARY > 0 and PRIMARY[Random.new(seed):NextInteger(1, #PRIMARY)]
	if gzone == zone and not st.golden and #rest > 0 then
		local s = rest[Random.new(seed + 17):NextInteger(1, #rest)]
		table.insert(list, { id = "g1", kind = "Golden", index = 1, pos = v3(s.pos) })
	end
	local tk = pick(Random.new(seed + z.order * 104729 + 1), reachable(z.tokens), E.dailyTokens)
	for i, s in tk do
		if not st.token[i] then table.insert(list, { id = "t" .. i, kind = "Token", index = i, pos = v3(s.pos) }) end
	end
	mine[player] = { zone = zone, hero = hero, day = st.day, list = list }
	local send = {}
	for _, c in list do table.insert(send, { id = c.id, kind = c.kind, pos = c.pos + PICKUP_LIFT }) end
	notify(player, "pickups", { zone = zone, hero = hero, list = send, fractals = st.fractalCount,
		tokens = st.tokenCount, golden = st.golden })
end
Players.PlayerRemoving:Connect(function(player) mine[player] = nil end)
local function checkPickups()
	local today = os.date("!%Y-%m-%d")
	for player, m in mine do
		if m.day ~= today then
			task.spawn(assignPickups, player) -- a new day: new pickups
			continue
		end
		local hrp = player.Character and player.Character:FindFirstChild("HumanoidRootPart")
		if not hrp or zoneOf(player) ~= m.zone then continue end
		for i = #m.list, 1, -1 do
			local c = m.list[i]
			if (hrp.Position - (c.pos + PICKUP_LIFT)).Magnitude < H.collectRadius + 1 then
				table.remove(m.list, i)
				local ok, info = _G.SPSO_Economy.collectDaily(player, m.hero, c.kind, c.index)
				notify(player, "collect", { id = c.id, kind = c.kind, pos = c.pos + PICKUP_LIFT, ok = ok, info = info })
			end
		end
	end
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
local VARIANTS = { male = { "CivilianMale1", "CivilianMale2", "CivilianMale3", "CivilianMale4" },
	female = { "CivilianFemale1", "CivilianFemale2", "CivilianFemale3", "CivilianFemale4" } }
local function startCivilians(zoneName: string, z, zf: Instance)
	for i, path in z.npcPaths do
		if #path < 2 then continue end
		for k = 1, 2 do -- the original's random-gender spawns: two walkers per path, any of the four looks
			local set = VARIANTS[math.random() < 0.5 and "male" or "female"]
			local name = set[math.random(#set)]
			local start = math.random(#path)
			local m = spawnModel(name, CFrame.new(v3(path[start]) + Vector3.new(0, 3.5, 0)), zf)
			if not m then continue end
			m:SetAttribute("SPSO_Walk", true)
			local hum = m:FindFirstChildOfClass("Humanoid")
			hum.WalkSpeed = H.npcWalkSpeed
			hum.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
			hum:SetStateEnabled(Enum.HumanoidStateType.Climbing, false)
			pcall(function() m.HumanoidRootPart:SetNetworkOwner(nil) end)
			table.insert(civilians, { model = m, hum = hum, path = path, node = start, dir = k == 1 and 1 or -1, wait = 0,
				last = m.HumanoidRootPart.Position, stuck = 0, zone = zoneName })
		end
	end
end
local function walkCivilians(dt: number)
	local occupied = {}
	for _, p in Players:GetPlayers() do
		local z = zoneOf(p)
		if z then occupied[z] = true end
	end
	for _, c in civilians do
		local hrp = c.model:FindFirstChild("HumanoidRootPart")
		if not hrp or not c.model.Parent then continue end
		-- nobody in the zone: the walkers wait in place (anchored, no physics) until a hero arrives
		if not occupied[c.zone] then
			if not c.parked then
				c.parked = true
				hrp.Anchored = true
			end
			continue
		elseif c.parked then
			c.parked = false
			hrp.Anchored = false
			c.last, c.stuck = hrp.Position, 0
		end
		if c.wait > now() then
			c.last, c.stuck = hrp.Position, 0
			continue
		end
		local target = v3(c.path[c.node])
		local flat = Vector3.new(1, 0, 1)
		local arrived = (hrp.Position * flat - target * flat).Magnitude < 3
		-- stuck (a corner, a kerb): after 3 s move on to the next node, after 8 s put the walker on it
		if (hrp.Position - c.last).Magnitude < 0.5 then c.stuck += dt else c.stuck = 0 end
		c.last = hrp.Position
		if c.stuck > 8 then
			c.model:PivotTo(CFrame.new(target + Vector3.new(0, 3.5, 0)))
			c.stuck, arrived = 0, true
		elseif c.stuck > 3 and c.stuck - dt <= 3 then
			arrived = true
		end
		if arrived then
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

-- pigeons: the original social-zone pigeon (pigeon_01) pecks around its spot, takes off when a hero runs at it,
-- flies away and lands back after a while
local pigeonParams = RaycastParams.new()
pigeonParams.FilterType = Enum.RaycastFilterType.Include
local function startPigeons(zoneName: string, z, zf: Instance)
	pigeonParams.FilterDescendantsInstances = { hubRoot }
	for _, pos in z.pigeons do
		local at = v3(pos)
		local hit = workspace:Raycast(at + Vector3.new(0, 4, 0), Vector3.new(0, -12, 0), pigeonParams)
		local floor = hit and hit.Position or at
		local m = spawnModel("HubPigeon", CFrame.new(floor + Vector3.new(0, 3, 0)), zf)
		if not m then return end
		local hrp = m:FindFirstChild("HumanoidRootPart")
		local hum = m:FindFirstChildOfClass("Humanoid")
		hrp.Anchored = true
		if hum then hum.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None end
		local lift = (hum and hum.HipHeight or 0) + hrp.Size.Y / 2
		local home = CFrame.new(floor + Vector3.new(0, lift, 0)) * CFrame.Angles(0, math.random() * math.pi * 2, 0)
		m:PivotTo(home)
		table.insert(pigeons, { model = m, home = home, zone = zoneName, state = "idle", t = 0, peck = now() + math.random() * 6 })
	end
end
local function stepPigeons(dt: number)
	for _, pg in pigeons do
		if not pg.model.Parent then continue end
		local pos = pg.model:GetPivot().Position
		if pg.state == "idle" then
			if now() > pg.peck then -- the second idle (pecking) now and then
				pg.peck = now() + 4 + math.random() * 6
				action(pg.model, "movement_idle_2")
			end
			for _, h in heroesIn(pg.zone) do
				if (h.hrp.Position - pos).Magnitude < H.pigeonScare then
					pg.state, pg.t = "takeoff", 0
					local away = (pos - h.hrp.Position) * Vector3.new(1, 0, 1)
					away = away.Magnitude > 0.1 and away.Unit or Vector3.xAxis
					away = (CFrame.Angles(0, (math.random() - 0.5) * 1.2, 0) * away)
					pg.vel = away * 20 + Vector3.new(0, 12, 0)
					pg.model:PivotTo(CFrame.lookAt(pos, pos + away))
					action(pg.model, math.random() < 0.5 and "fly_takeoff" or "fly_takeoff_2")
					break
				end
			end
		elseif pg.state == "takeoff" or pg.state == "fly" then
			pg.t += dt
			if pg.state == "takeoff" and pg.t > 0.35 then
				pg.state = "fly"
				action(pg.model, "fly")
			end
			if pg.t > 0.2 then
				local p = pos + pg.vel * math.min(pg.t, 1) * dt
				pg.model:PivotTo(CFrame.lookAt(p, p + pg.vel * Vector3.new(1, 0, 1) + Vector3.new(0, 0.01, 0)))
			end
			if pg.t > 4 then
				pg.state, pg.t = "gone", 0
				pg.model:PivotTo(pg.home + Vector3.new(0, -500, 0))
				action(pg.model, "none")
			end
		elseif pg.state == "gone" then
			pg.t += dt
			if pg.t > H.pigeonRespawn then
				local busy = false -- only come back when nobody is standing on the spot
				for _, h in heroesIn(pg.zone) do
					if (h.hrp.Position - pg.home.Position).Magnitude < H.pigeonScare * 1.5 then busy = true end
				end
				if not busy then
					pg.state, pg.t = "idle", 0
					pg.model:PivotTo(pg.home)
					action(pg.model, math.random() < 0.5 and "fly_land" or "fly_land_2")
					pg.peck = now() + 3 + math.random() * 4
				end
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
		notify(player, "star", { pos = base.Position + Vector3.new(0, 4, 0) })
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
		local label = ({ store = "Shop", snack = "Snack Stand", arcade = "Arcade" })[s.kind] or s.kind
		prompt(a, "Browse", label, 8).Triggered:Connect(function(player)
			if zoneOf(player) ~= zoneName then return end
			if s.kind == "store" then
				notify(player, "openStore", {})
			else
				notify(player, "message", { text = "The " .. label .. " is coming soon!" })
			end
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

local lastCollect, lastWalk = 0, now()
RunService.Heartbeat:Connect(function(dt)
	stepPigeons(dt)
	local t = now()
	if t - lastWalk > 0.5 then
		walkCivilians(t - lastWalk)
		lastWalk = t
	end
	if t - lastCollect < 0.15 then return end
	lastCollect = t
	checkPickups()
end)
