-- SPSO brawler server. Heroes and enemies are "fighters" driven by the original game data (GameData):
--   * every hero's L1-L5 chain, R1-R3 power attacks (power cost) and super; the clips' own AnimationEvents
--     (OnCollisionEnable/Disable, OnProjectileFire, OnChainAttack) time each impact, through a headless
--     ExactAnimator per fighter that also gives the exact bone positions of the attack colliders
--   * impact types: melee colliders (spheres on bones), projectiles (speed, lifespan, gravity, explosion),
--     beams, target impacts; damage, recoil type (small/big/getup/knockdown/launch/stun), pushback, launch
--   * power gain from damage dealt and received, combo heat, KO scoring, survival bonus, medals
--   * enemy archetypes (melee thugs, ranged blasters, the warlord boss) with their original stats
--   * hero select, waves, pickups
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local ServerStorage = game:GetService("ServerStorage")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local GameData = require(Game:WaitForChild("GameData"))
local Assets = require(Game:WaitForChild("Assets"))
local Net = require(Game:WaitForChild("Net"))
local HeroPack = require(SPSO:WaitForChild("Runtime"):WaitForChild("HeroPack"))
local ExactAnimator = require(SPSO.Runtime:WaitForChild("ExactAnimator"))

local MissionData = Config.Mission and require(Game:WaitForChild("MissionData")) or nil
local StageBuilder = Config.Mission and require(Game:WaitForChild("StageBuilder")) or nil

local AttackRemote, EmoteRemote, FxRemote = Net.event("Attack"), Net.event("Emote"), Net.event("Fx")
local SelectRemote = Net.event("SelectHero")
local S = GameData.Scoring

Players.CharacterAutoLoads = false
Players.RespawnTime = Config.RespawnTime
workspace.Gravity = GameData.Heroes[Config.DefaultHero].gravity

local arena = workspace:WaitForChild(Config.Map, 30)
local spawns = arena and arena:FindFirstChild("Spawns")
local enemyFolder = workspace:FindFirstChild("SPSO_Enemies") or Instance.new("Folder")
enemyFolder.Name = "SPSO_Enemies"
enemyFolder.Parent = workspace
local pickupFolder = workspace:FindFirstChild("SPSO_Pickups") or Instance.new("Folder")
pickupFolder.Name = "SPSO_Pickups"
pickupFolder.Parent = workspace

local fighters = {}
local projectiles = {}
local pickups = {}
local seq, projSeq = 0, 0
local now = os.clock
local Score = { team = 0, deaths = 0, kos = 0, running = false }
local Stats = { attacks = 0, opens = 0, checks = 0, hits = 0, projectiles = 0, beams = 0 }
_G.SPSO_Stats, _G.SPSO_Fighters = Stats, fighters -- for playtest tooling

local function flat(v: Vector3): Vector3
	return Vector3.new(v.X, 0, v.Z)
end

local Mission = { stage = nil, folder = nil, crates = {} } -- the running original mission (Config.Mission)

local function spawnPoint(prefix: string, i: number): CFrame
	if Mission.stage and prefix == "Player" and #Mission.stage.players > 0 then
		local pl = Mission.stage.players
		return StageBuilder.cf(pl[(i - 1) % #pl + 1])
	end
	local pts = {}
	if spawns then
		for _, p in spawns:GetChildren() do
			if p:IsA("BasePart") and string.sub(p.Name, 1, #prefix) == prefix then table.insert(pts, p) end
		end
		table.sort(pts, function(a, b) return a.Name < b.Name end)
	end
	if #pts == 0 then return CFrame.new(0, 6, prefix == "Player" and 25 or -25) end
	return pts[(i - 1) % #pts + 1].CFrame
end

local wallParams = RaycastParams.new()
wallParams.FilterType = Enum.RaycastFilterType.Include
wallParams.FilterDescendantsInstances = { arena and arena:FindFirstChild("Collision") or workspace.Terrain }
local function setWalls(folder)
	wallParams.FilterDescendantsInstances = { folder or workspace.Terrain }
end

-- fighters ------------------------------------------------------------------------------------------------------
local Fighter = {}
Fighter.__index = Fighter

function Fighter.new(model: Model, team: string, player: Player?, hero: string, archetype: string?)
	local f = setmetatable({}, Fighter)
	f.model, f.team, f.player, f.hero, f.arch = model, team, player, hero, archetype
	f.data = archetype and GameData.Enemies[archetype] or GameData.Heroes[hero]
	f.ai = archetype and Config.Enemies[archetype] or nil
	f.damageScale = f.ai and f.ai.damageScale or 1
	f.radius = (f.data.radius and f.data.radius > 0) and f.data.radius or Config.TargetRadius
	f.hum = model:FindFirstChildOfClass("Humanoid")
	f.hrp = model:FindFirstChild("HumanoidRootPart")
	local m6 = f.hrp and f.hrp:FindFirstChild("RigRoot")
	f.rigC0 = m6 and m6.C0 or CFrame.new(0, -3.3, 0)
	f.power, f.heat = 0, 0
	f.chainKind, f.chainIndex, f.chainOpen, f.buffered = nil, 0, false, nil
	f.action, f.actionKind, f.atk = nil, nil, nil
	f.dead = false
	f.nextThink, f.nextAttack, f.launchAt, f.stunUntil, f.nextSuper = 0, now() + 1.5, nil, nil, now() + 8
	f.actionStart, f.stunImmuneUntil, f.lastHitAt = 0, 0, 0
	f.anim = ExactAnimator.new(HeroPack.get(hero), nil, { headless = true, wrapModes = Config.WrapModes })
	f.anim.Event:Connect(function(fn, data, clip) f:onEvent(fn, data, clip) end)
	model:SetAttribute("SPSO_Hero", hero)
	model:SetAttribute("SPSO_Archetype", archetype)
	model:SetAttribute("SPSO_Team", team)
	model:SetAttribute("SPSO_Dead", false)
	model:SetAttribute("SPSO_Lock", false)
	CollectionService:AddTag(model, "SPSO_Fighter")
	fighters[model] = f
	return f
end

function Fighter:rigCF(): CFrame
	return self.hrp.CFrame * self.rigC0
end

function Fighter:nodePos(node: string?, offset): Vector3
	local root = self:rigCF()
	local ncf = node and self.anim:NodeCFrame(node)
	if not ncf then return (root * CFrame.new(0, 3.5, -1.5)).Position end
	local o = offset and Vector3.new(offset[1], offset[2], offset[3]) or Vector3.zero
	return (root * ncf * CFrame.new(o)).Position
end

function Fighter:colliderPos(imp): Vector3
	local col = self.data.colliders and self.data.colliders[imp.collider]
	return self:nodePos(col and col.node or "fx_Rpalm", col and col.offset)
end

function Fighter:chest(): Vector3
	return self.hrp.Position + Vector3.new(0, 0.6, 0)
end

function Fighter:play(clip: string, fade: number, kind: string, attackKey: string?)
	seq += 1
	local anim = self.anim
	if anim:IsPlaying(clip) then anim:Stop(clip) end
	anim:CrossFade(clip, fade)
	self.action, self.actionKind = clip, kind
	self.actionStart = now()
	self.chainOpen = false
	self.atk = nil
	if attackKey then
		local def = self.data.attacks[attackKey]
		self.atk = { key = attackKey, def = def, open = {}, hits = {}, count = {}, fired = {}, timed = {}, nextProj = 1 }
	end
	self.model:SetAttribute("SPSO_Action", string.format("%s|%.4f|%.3f|%d", clip, workspace:GetServerTimeNow(), fade, seq))
	self.model:SetAttribute("SPSO_Lock", kind ~= "emote")
end

function Fighter:clear()
	seq += 1
	self.action, self.actionKind, self.atk = nil, nil, nil
	self.chainKind, self.chainIndex, self.chainOpen = nil, 0, false
	self.launchAt, self.stunUntil = nil, nil
	self.anim:Stop()
	self.model:SetAttribute("SPSO_Action", string.format("none|%.4f|0.2|%d", workspace:GetServerTimeNow(), seq))
	self.model:SetAttribute("SPSO_Lock", false)
end

function Fighter:addPower(n: number)
	self.power = math.clamp(self.power + n, 0, Config.SuperCost)
	if self.player then self.player:SetAttribute("SPSO_Power", self.power) end
end

function Fighter:addHeat(n: number)
	self.heat = math.clamp(self.heat + n, 0, S.comboMax)
	if self.player then self.player:SetAttribute("SPSO_Combo", self.heat) end
end

-- impacts --------------------------------------------------------------------------------------------------------
local function inBrawler(f): boolean -- heroes in a social zone are out of the fight
	return not f.player or Config.Mode ~= "Hub" or f.player:GetAttribute("SPSO_Zone") == "Brawler"
end
local function opponents(f)
	local out = {}
	for _, t in fighters do
		if t ~= f and t.team ~= f.team and not t.dead and t.hrp and t.hrp.Parent and inBrawler(t) then table.insert(out, t) end
	end
	return out
end

function Fighter:nearestOpponent(maxDist: number?, inFront: boolean?)
	local best, bd = nil, maxDist or math.huge
	local look = flat(self.hrp.CFrame.LookVector)
	for _, t in opponents(self) do
		local off = flat(t.hrp.Position - self.hrp.Position)
		local d = off.Magnitude
		if d < bd and (not inFront or d < 4 or look:Dot(off.Unit) > 0.2) then best, bd = t, d end
	end
	return best, bd
end

local function bodyDistance(t, p: Vector3): number
	local base = t.hrp.Position
	local y = math.clamp(p.Y, base.Y - 3.3, base.Y + 2.2)
	return (Vector3.new(base.X, y, base.Z) - p).Magnitude
end

function Fighter:canHit(i: number, imp, t): boolean
	local a = self.atk
	a.hits[i] = a.hits[i] or {}
	a.count[i] = a.count[i] or 0
	if (a.hits[i][t] or 0) >= math.max(1, imp.maxHits) then return false end
	if imp.maxTargets > 0 and a.count[i] >= imp.maxTargets then return false end
	return true
end

function Fighter:registerHit(i: number, t)
	local a = self.atk
	a.hits[i][t] = (a.hits[i][t] or 0) + 1
	a.count[i] += 1
end

local breakCrate -- mission crates (defined with the mission code)
function Fighter:meleeCheck(i: number, imp)
	local pos = self:colliderPos(imp)
	if self.team == "Hero" then Stats.checks += 1 end
	local r = math.max(1.2, imp.radius) * Config.HitRadiusScale
	for _, t in opponents(self) do
		if self:canHit(i, imp, t) and bodyDistance(t, pos) <= r + t.radius then
			self:registerHit(i, t)
			t:takeHit(self, imp, pos)
		end
	end
	if self.team == "Hero" and breakCrate then
		for crate, c in Mission.crates do
			if not c.broken and (c.pos - pos).Magnitude <= r + c.radius then breakCrate(crate, self) end
		end
	end
end

function Fighter:aimDir(from: Vector3, range: number): Vector3
	local tgt = self:nearestOpponent(range + 6, true)
	if tgt then
		local d = tgt:chest() - from
		if d.Magnitude > 0.1 then return d.Unit end
	end
	return flat(self.hrp.CFrame.LookVector).Unit
end

function Fighter:fireBeam(i: number, imp)
	local def = self.atk.def
	local from = self:colliderPos(imp)
	local range = math.max(def.range, 20)
	local dir = self:aimDir(from, range)
	local hitT, hitAt, best = nil, nil, range
	local r = math.max(1, imp.radius) * Config.HitRadiusScale
	for _, t in opponents(self) do
		local rel = t:chest() - from
		local along = rel:Dot(dir)
		if along > 0 and along < best and (rel - dir * along).Magnitude <= r + t.radius then
			hitT, best, hitAt = t, along, from + dir * along
		end
	end
	local to = hitAt or (from + dir * range)
	local wall = workspace:Raycast(from, to - from, wallParams)
	if wall and (not hitAt or (wall.Position - from).Magnitude < best) then
		to, hitT = wall.Position, nil
	end
	FxRemote:FireAllClients("beam", { hero = self.hero, from = from, to = to })
	if hitT and self:canHit(i, imp, hitT) then
		self:registerHit(i, hitT)
		hitT:takeHit(self, imp, to)
	end
end

function Fighter:fireProjectile(i: number, imp)
	local from = self:colliderPos(imp)
	local speed = imp.speed > 0 and imp.speed or 38
	local life = imp.life > 0 and imp.life or 3
	local dir = imp.aimed ~= false and self:aimDir(from, speed * life) or flat(self.hrp.CFrame.LookVector).Unit
	projSeq += 1
	local p = { id = projSeq, owner = self, imp = imp, idx = i, pos = from, vel = dir * speed,
		g = imp.gravity or 0, expires = now() + life, hit = {}, atkRef = self.atk }
	projectiles[p.id] = p
	FxRemote:FireAllClients("proj", { id = p.id, from = from, vel = p.vel, life = life, g = p.g, kind = imp.visual or "orb",
		hero = self.arch and "Shared" or self.hero, team = self.team })
end

function Fighter:targetImpact(i: number, imp)
	local tgt = self:nearestOpponent((self.atk.def.range or 10) + 4, true)
	if tgt and self:canHit(i, imp, tgt) then
		self:registerHit(i, tgt)
		tgt:takeHit(self, imp, tgt:chest())
	end
end

function Fighter:triggerImpact(i: number, open: boolean)
	local imp = self.atk.def.impacts[i]
	if not imp then return end
	if imp.type == 2 then
		if open then self:fireBeam(i, imp) end
	elseif imp.type == 3 then
		if open then self:targetImpact(i, imp) end
	elseif imp.type ~= 1 then
		self.atk.open[i] = open or nil
		if open and self.team == "Hero" then Stats.opens += 1 end
		if open then self:meleeCheck(i, imp) end
	end
end

function Fighter:onEvent(fn: string, data: string, clip: string)
	if clip ~= self.action or not self.model.Parent then return end
	local a = self.atk
	if fn == "OnChainAttackAnimTag" then
		if not self.chainOpen then
			self.chainOpen = true
			if self.buffered then
				local k = self.buffered
				self.buffered = nil
				self:tryAttack(k)
			end
		end
		return
	end
	if not a then return end
	local idx = tonumber(data)
	if fn == "OnCollisionEnableAnimTag" or fn == "OnCollisionDisableAnimTag" then
		local open = fn == "OnCollisionEnableAnimTag"
		if idx then
			self:triggerImpact(idx, open)
		else
			for i, imp in a.def.impacts do
				if imp.type ~= 1 then self:triggerImpact(i, open) end
			end
		end
	elseif fn == "OnProjectileFireAnimTag" then
		local i
		if a.def.repeatFire then
			i = 1
		elseif idx and a.def.impacts[idx] and a.def.impacts[idx].type == 1 then
			i = idx
		else
			for k = a.nextProj, #a.def.impacts do
				if a.def.impacts[k].type == 1 then i = k break end
			end
			a.nextProj = (i or #a.def.impacts) + 1
		end
		if i and a.def.impacts[i] then self:fireProjectile(i, a.def.impacts[i]) end
	end
end

-- impacts the clip has no AnimationEvents for: the data's own timings, else the middle of the clip
function Fighter:timedImpacts()
	local a = self.atk
	local st = self.anim:GetState(self.action)
	local t, dur = st and st.time or 0, math.max(0.1, a.def.duration or (st and st.length) or 1)
	for i, imp in a.def.impacts do
		if imp.type == 1 then
			if a.def.events.projectile == 0 and not a.timed[i] then
				local at = imp.fire > 0 and imp.fire or dur * 0.4
				if t >= at then
					a.timed[i] = true
					self:fireProjectile(i, imp)
				end
			end
		elseif a.def.events.collision == 0 then
			local t0, t1 = imp.start, imp.stop
			if not (t1 > t0 and t0 >= 0) then t0, t1 = dur * 0.35, dur * 0.6 end
			if not a.timed[i] and t >= t0 then
				a.timed[i] = 1
				self:triggerImpact(i, true)
			elseif a.timed[i] == 1 and t >= t1 then
				a.timed[i] = 2
				self:triggerImpact(i, false)
			end
		end
	end
end

-- attacks -------------------------------------------------------------------------------------------------------
local CHAIN_L = { "L1", "L2", "L3", "L4", "L5" }

function Fighter:startAttack(key: string): boolean
	local def = self.data.attacks[key]
	if not def or not self.anim:HasClip(def.anim) then return false end
	if self.team == "Hero" and def.cost > 0 then
		if self.power + 1e-6 < def.cost then
			if self.player then FxRemote:FireClient(self.player, "denied", { need = def.cost }) end
			return false
		end
		self:addPower(-def.cost)
	end
	self:play(def.anim, Config.FadeAttack, "attack", key)
	Stats.attacks += 1
	return true
end

function Fighter:tryAttack(kind: string)
	if self.dead or self.actionKind == "death" then return end
	if self.actionKind == "recoil" then
		local cancel = self.team == "Hero" and (self.action == "recoil_small" or self.action == "recoil_big")
			and now() - self.actionStart >= Config.RecoilCancel
		if not cancel then return end
		self:clear()
	end
	local busy = self.actionKind == "attack"
	if busy and not self.chainOpen then
		self.buffered = kind
		return
	end
	if kind == "L" then
		local idx = (busy and self.chainKind == "L") and self.chainIndex + 1 or 1
		if not CHAIN_L[idx] then idx = 1 end
		if self:startAttack(CHAIN_L[idx]) then self.chainKind, self.chainIndex = "L", idx end
	elseif kind == "R" or kind == "R1" or kind == "R2" or kind == "R3" or kind == "Super" then
		local key = kind == "R" and "R1" or kind
		if self:startAttack(key) then self.chainKind, self.chainIndex = key, 1 end
	end
end

-- hits ------------------------------------------------------------------------------------------------------------
local function enemiesLeft(): number
	local n = 0
	for _, f in fighters do
		if f.team == "Enemy" and not f.dead then n += 1 end
	end
	return n
end

local function publishScore()
	local bonus = S.survivalBonus[math.min(Score.deaths, 3) + 1] or 1
	SPSO:SetAttribute("TeamScore", math.floor(Score.team * bonus + 0.5))
	SPSO:SetAttribute("SurvivalBonus", bonus)
end

local function dropPickups(pos: Vector3)
	local function drop(kind)
		local p = Instance.new("Part")
		p.Name = "Pickup_" .. kind
		p.Shape = Enum.PartType.Ball
		p.Size = Vector3.one * 1.6
		p.Material = Enum.Material.Neon
		p.Color = kind == "star" and Color3.fromRGB(255, 214, 64) or Color3.fromRGB(255, 80, 110)
		p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch = true, false, false, false
		p.Position = pos + Vector3.new(math.random() * 4 - 2, 1.5, math.random() * 4 - 2)
		p:SetAttribute("Kind", kind)
		p.Parent = pickupFolder
		pickups[p] = now() + 14
	end
	if math.random() < Config.PickupChance.star then drop("star") end
	if math.random() < Config.PickupChance.health then drop("health") end
end

function Fighter:die(attacker, imp)
	if self.dead then return end
	self.dead = true
	self.buffered = nil
	self.model:SetAttribute("SPSO_Dead", true)
	if self.team == "Enemy" then
		SPSO:SetAttribute("EnemiesLeft", enemiesLeft())
		if attacker and attacker.team == "Hero" then
			local rank = math.clamp(self.data.rank or 1, 0, 5)
			local mult = math.floor(math.max(0, math.min(attacker.heat, S.comboMax - 1))) + 1
			local pts = (S.koValues[rank + 1] or 100) * mult
			Score.team += pts
			Score.kos += 1
			publishScore()
			FxRemote:FireAllClients("score", { pos = self:chest() + Vector3.new(0, 3, 0), points = pts, mult = mult })
		end
		if not Mission.stage then dropPickups(self.hrp.Position) end
		if self.ai and self.ai.boss then FxRemote:FireAllClients("bossKO", { pos = self:chest() }) end
		if self.onKilled then task.spawn(self.onKilled, self) end
		if imp and (imp.recoil == 5 or imp.recoil == 4) then
			self.hum:ChangeState(Enum.HumanoidStateType.Freefall)
			local dir = attacker and flat(self.hrp.Position - attacker.hrp.Position) or Vector3.zero
			dir = dir.Magnitude > 0.1 and dir.Unit or -self.hrp.CFrame.LookVector
			self.hrp.AssemblyLinearVelocity = dir * math.max(12, imp.pushback) + Vector3.new(0, math.max(20, imp.launch), 0)
			self:play("recoil_launch", Config.FadeRecoil, "death")
			task.delay(0.75, function()
				if self.model.Parent then self:play("recoil_launch_land", 0.05, "death") end
			end)
		else
			self:play("recoil_death", Config.FadeRecoil, "death")
		end
		task.delay(Config.DespawnAfter, function()
			fighters[self.model] = nil
			self.model:Destroy()
			if self.onDespawn then self.onDespawn(self) end
		end)
	else
		Score.deaths += 1
		publishScore()
		self:addHeat(-S.comboMax)
		self:play("recoil_death", Config.FadeRecoil, "death")
		if self.hrp then self.hrp.Anchored = true end
	end
end

local RECOIL = { [1] = "small", [2] = "big", [3] = "getup", [4] = "knockdown", [5] = "launch", [6] = "small", [7] = "stun", [8] = "small" }

local fireEvent -- scenario events (mission code)
function Fighter:takeHit(attacker, imp, src: Vector3?)
	if self.dead then return end
	if self.asleep and self.wakeOnHit ~= false then self.asleep = false end
	if imp.event and fireEvent and attacker.team == "Enemy" then fireEvent(imp.event) end
	if attacker.team == "Hero" then Stats.hits += 1 end
	local dmg = imp.damage * (attacker.damageScale or 1)
	self.hum.Health = math.max(0, self.hum.Health - dmg)
	if attacker.team == "Hero" then
		attacker:addPower(dmg * (attacker.data.powerDealt or 0.5))
		attacker:addHeat(dmg * S.comboGainPerDamage)
	end
	if self.team == "Hero" then
		self:addPower(dmg * (self.data.powerReceived or 0.5))
		self:addHeat(-dmg * S.comboLossPerDamage)
	end
	local recoil = imp.recoil or 1
	local limit = self.data.recoilLimit or 0
	if limit > 0 and recoil > limit then recoil = limit end
	FxRemote:FireAllClients("hit", {
		pos = src or self:chest(), amount = math.floor(dmg + 0.5), heavy = recoil >= 2, team = self.team,
		hero = attacker.arch and "Shared" or attacker.hero, effect = imp.effect, victim = self.model,
	})
	if self.team == "Enemy" and attacker.hrp then
		local dir = flat(attacker.hrp.Position - self.hrp.Position)
		if dir.Magnitude > 0.1 then self.hrp.CFrame = CFrame.lookAt(self.hrp.Position, self.hrp.Position + dir) end
	end
	if self.hum.Health <= 0 then
		self:die(attacker, imp)
		return
	end
	self.lastHitAt = now()
	local reaction = RECOIL[recoil]
	if not reaction then return end -- 0 none, 9 uninterruptible: damage only
	if self.ai and self.ai.boss and (reaction == "small") and self.actionKind == "attack" then return end
	if self.team == "Hero" then
		if now() < self.stunImmuneUntil then return end
		self.stunImmuneUntil = now() + Config.HeroStunImmunity
		if reaction == "launch" or reaction == "knockdown" or reaction == "getup" then reaction = "big" end
	end
	self.buffered = nil
	-- pushback away from the attacker (or from the collider), launch upward
	local from = (imp.fromCollider and src) or attacker.hrp.Position
	local dir = flat(self.hrp.Position - from)
	dir = dir.Magnitude > 0.05 and dir.Unit or -self.hrp.CFrame.LookVector
	local push = dir * (imp.pushback or 0) * (1 - math.clamp(self.data.pushbackResist or 0, 0, 1))
	local up = (reaction == "launch" or reaction == "knockdown") and math.max(imp.launch or 0, reaction == "knockdown" and 8 or 18) or 0
	if self.team == "Hero" then
		if self.player and push.Magnitude > 0.1 then FxRemote:FireClient(self.player, "push", { vel = push, time = imp.pushTime }) end
	else
		if up > 0 then self.hum:ChangeState(Enum.HumanoidStateType.Freefall) end
		self.hrp.AssemblyLinearVelocity = push + Vector3.new(0, up, 0)
	end
	if reaction == "launch" or reaction == "knockdown" then
		self:play("recoil_launch", Config.FadeRecoil, "recoil")
		self.launchAt = now()
	elseif reaction == "getup" then
		self:play("recoil_getup", Config.FadeRecoil, "recoil")
	elseif reaction == "stun" then
		self:play("recoil_stun", Config.FadeRecoil, "recoil")
		self.stunUntil = now() + math.max(1.2, imp.recoilTime or 0)
	else
		self:play(reaction == "big" and "recoil_big" or "recoil_small", Config.FadeRecoil, "recoil")
	end
	if self.team == "Enemy" then self.nextAttack = math.max(self.nextAttack, now() + 0.9) end
end

function Fighter:onActionEnd()
	local clip, kind = self.action, self.actionKind
	if kind == "death" then return end
	local tp = self.ai and self.ai.teleport
	if tp and clip == tp[1] then -- the warlord reappears next to a hero and strikes
		local t = self:nearestOpponent()
		if t then
			local dir = flat(self.hrp.Position - t.hrp.Position)
			dir = dir.Magnitude > 0.1 and dir.Unit or Vector3.zAxis
			local pos = t.hrp.Position + dir * 6
			self.hrp.CFrame = CFrame.lookAt(pos, Vector3.new(t.hrp.Position.X, pos.Y, t.hrp.Position.Z))
		end
		self:play(tp[2], Config.FadeAttack, "attack", self.data.attacks[tp[2]] and tp[2] or nil)
		return
	end
	if clip == "recoil_launch_land" then
		self:play("recoil_getup", 0.1, "recoil")
		return
	end
	local b = self.buffered
	self.buffered = nil
	self:clear()
	if b then self:tryAttack(b) end
end

-- enemy AI --------------------------------------------------------------------------------------------------------
local function attackersNow(): number
	local n = 0
	for _, o in fighters do
		if o.team == "Enemy" and o.actionKind == "attack" then n += 1 end
	end
	return n
end

function Fighter:pickAttack(dist: number)
	local keys = {}
	local tp = self.ai.teleport
	for k, a in self.data.attacks do
		if k ~= "Super" and not (tp and k == tp[2]) and not (self.ai.noAttacks and self.ai.noAttacks[k])
			and (dist <= a.range + 6 or self.ai.keepDistance > 0) then table.insert(keys, k) end
	end
	if self.ai.boss and now() >= self.nextSuper and self.data.attacks.Super then
		self.nextSuper = now() + self.ai.superEvery
		return "Super"
	end
	if #keys == 0 then return nil end
	return keys[math.random(#keys)]
end

local shapeshift -- mission code
function Fighter:think()
	local t = now()
	if self.dead or t < self.nextThink or self.spawningIn then return end
	self.nextThink = t + self.ai.think
	if self.action then
		self.hum.WalkSpeed = 0
		return
	end
	self.hum.WalkSpeed = self.data.speed * (self.speedScale or 1)
	local best, bd = self:nearestOpponent()
	if self.asleep then
		if best and bd <= (self.aggro or 50) then self.asleep = false else best = nil end
	end
	if not best then
		self.hum:Move(Vector3.zero)
		return
	end
	if self.ai.shifter and shapeshift and not self.shifted and t >= (self.shiftAt or math.huge) then
		self.shifted = true
		shapeshift(self)
		return
	end
	local dir = flat(best.hrp.Position - self.hrp.Position)
	local reach = 0
	for _, a in self.data.attacks do reach = math.max(reach, a.range) end
	local keep = self.ai.keepDistance
	local engage = keep > 0 and math.max(keep + 6, reach) or math.max(4.5, math.min(reach, 8) + self.radius + best.radius)
	if keep > 0 and bd < keep - 4 then
		self.hum:MoveTo(self.hrp.Position - dir.Unit * 8)
		return
	end
	if bd > engage then
		local push = Vector3.zero
		for _, o in fighters do
			if o ~= self and o.team == "Enemy" and not o.dead and o.hrp then
				local away = flat(self.hrp.Position - o.hrp.Position)
				if away.Magnitude < 6 and away.Magnitude > 0.01 then push += away.Unit * (6 - away.Magnitude) end
			end
		end
		self.hum:MoveTo(best.hrp.Position - dir.Unit * (engage * 0.75) + push)
		return
	end
	self.hum:Move(Vector3.zero)
	self.hrp.CFrame = CFrame.lookAt(self.hrp.Position, self.hrp.Position + dir)
	if t >= self.nextAttack and (self.ai.boss or attackersNow() < Config.MaxAttackers)
		and t - best.lastHitAt > Config.WaitAfterHeroHit then
		local key = self:pickAttack(bd)
		if key then
			self:play(self.data.attacks[key].anim, Config.FadeAttack, "attack", key)
			local c = self.ai.cooldown
			self.nextAttack = t + c[1] + math.random() * (c[2] - c[1])
		end
	end
end

-- frame loop ---------------------------------------------------------------------------------------------------------
local function stepProjectiles(dt: number)
	for id, p in projectiles do
		local owner = p.owner
		local from = p.pos
		p.vel += Vector3.new(0, -p.g * dt, 0)
		local to = from + p.vel * dt
		local done = now() >= p.expires
		local hitPos
		if not done then
			local wall = workspace:Raycast(from, to - from, wallParams)
			if wall then done, hitPos = true, wall.Position end
		end
		if not done and owner.team == "Hero" and breakCrate then
			for crate, c in Mission.crates do
				if not c.broken and (c.pos - to).Magnitude <= math.max(0.8, p.imp.radius) + c.radius then
					breakCrate(crate, owner)
					done, hitPos = true, to
				end
			end
		end
		if not done and owner.model.Parent then
			local r = math.max(0.8, p.imp.radius)
			for _, t in opponents(owner) do
				if not p.hit[t] and bodyDistance(t, to) <= r + t.radius then
					p.hit[t] = true
					hitPos = to
					t:takeHit(owner, p.imp, to)
					if (p.imp.explode or 0) > 0 then
						for _, o in opponents(owner) do
							if o ~= t and not p.hit[o] and bodyDistance(o, to) <= p.imp.explode + o.radius then
								p.hit[o] = true
								o:takeHit(owner, p.imp, to)
							end
						end
					end
					if p.imp.destroyOnImpact ~= false then done = true end
					break
				end
			end
		end
		p.pos = to
		if done then
			projectiles[id] = nil
			FxRemote:FireAllClients("projEnd", { id = id, pos = hitPos or to, hit = hitPos ~= nil, hero = owner.hero })
		end
	end
end

local function stepPickups()
	for p, expires in pickups do
		if not p.Parent or now() > expires then
			pickups[p] = nil
			p:Destroy()
		else
			for _, f in fighters do
				if f.team == "Hero" and not f.dead and f.hrp and (f.hrp.Position - p.Position).Magnitude < 4.5 then
					local kind = p:GetAttribute("Kind")
					if kind == "star" then
						Score.team += S.pickupBonus
						publishScore()
					else
						f.hum.Health = math.min(f.hum.MaxHealth, f.hum.Health + f.hum.MaxHealth * Config.HealthPickup)
					end
					if f.player then FxRemote:FireClient(f.player, "pickup", { kind = kind, pos = p.Position }) end
					pickups[p] = nil
					p:Destroy()
					break
				end
			end
		end
	end
end

RunService.Heartbeat:Connect(function(dt)
	for model, f in fighters do
		if not model.Parent then
			fighters[model] = nil
			continue
		end
		f.anim:Step(dt)
		local d = f.anim:ConsumeRootMotion()
		if f.team == "Enemy" and f.action and d ~= 0 and f.hrp then
			local clip = f.anim.pack.clips[f.action]
			if clip and clip.rootMotion then f.hrp.CFrame += f.hrp.CFrame.LookVector * d end
		end
		if f.player and f.heat > 0 then f:addHeat(-S.comboLossRate * dt) end
		if f.action == "recoil_launch" and f.launchAt and not f.dead and now() - f.launchAt > 0.75 then
			f.launchAt = nil
			f:play("recoil_launch_land", 0.05, "recoil")
		elseif f.action == "recoil_stun" and f.stunUntil and now() >= f.stunUntil then
			f:clear()
		elseif f.action and not f.anim:IsPlaying(f.action) then
			f:onActionEnd()
		end
		if f.atk and f.action then
			f:timedImpacts()
			for i in f.atk.open do
				local imp = f.atk.def.impacts[i]
				if imp then f:meleeCheck(i, imp) end
			end
		end
		if f.team == "Enemy" then f:think() end
	end
	stepProjectiles(dt)
	stepPickups()
end)

-- players and hero select ------------------------------------------------------------------------------------------------
local function setupCharacter(player: Player, char: Model, hero: string)
	local cfg = Config.Heroes[hero]
	local hum = char:FindFirstChildOfClass("Humanoid")
	hum.MaxHealth, hum.Health = cfg.health, cfg.health
	hum.BreakJointsOnDeath = false
	hum.WalkSpeed = cfg.walkSpeed
	hum.UseJumpPower = true
	hum.JumpPower = cfg.jumpPower
	local f = Fighter.new(char, "Hero", player, hero, nil)
	f.power = player:GetAttribute("SPSO_Power") or 0
	hum.Died:Connect(function()
		f:die(nil, nil)
		task.delay(Config.RespawnTime, function()
			if player.Parent and player.Character == char then
				_G.SPSO_SpawnHero(player)
			end
		end)
	end)
end

local function spawnHero(player: Player)
	local hero = player:GetAttribute("SPSO_Hero")
	local cfg = hero and Config.Heroes[hero]
	if not cfg then return end
	local template = ServerStorage.SPSO.Characters:FindFirstChild(cfg.template)
	if not template then
		warn("[SPSO] no character template " .. cfg.template)
		return
	end
	local old = player.Character
	if old then
		fighters[old] = nil
		old:Destroy()
	end
	local char = template:Clone()
	char.Name = player.Name
	local hubCF = _G.SPSO_SpawnCF and _G.SPSO_SpawnCF(player)
	char:PivotTo(hubCF or (spawnPoint("Player", (#Players:GetPlayers() + player.UserId) % 4 + 1) + Vector3.new(0, 3, 0)))
	char.Parent = workspace
	player.Character = char
	pcall(function() char.HumanoidRootPart:SetNetworkOwner(player) end)
	setupCharacter(player, char, hero)
	FxRemote:FireAllClients("spawn", { model = char })
end
_G.SPSO_SpawnHero = spawnHero

local function onPlayer(player: Player)
	player:SetAttribute("SPSO_Power", player:GetAttribute("SPSO_Power") or 0)
	player:SetAttribute("SPSO_Combo", 0)
end
Players.PlayerAdded:Connect(onPlayer)
for _, p in Players:GetPlayers() do task.spawn(onPlayer, p) end
Players.PlayerRemoving:Connect(function(p)
	if p.Character then
		fighters[p.Character] = nil
		p.Character:Destroy()
	end
end)

SelectRemote.OnServerEvent:Connect(function(player, hero)
	if type(hero) ~= "string" or not Config.Heroes[hero] then return end
	-- heroes are owned (store); the port's five are starter heroes everyone owns
	if _G.SPSO_Economy and not _G.SPSO_Economy.ownsHero(player, hero) then return end
	local f = player.Character and fighters[player.Character]
	if f and f.actionKind == "attack" then return end
	player:SetAttribute("SPSO_Hero", hero)
	spawnHero(player)
end)

AttackRemote.OnServerEvent:Connect(function(player, kind)
	if Config.Mode == "Hub" and player:GetAttribute("SPSO_Zone") ~= "Brawler" then return end
	local f = player.Character and fighters[player.Character]
	if f and type(kind) == "string" then f:tryAttack(kind) end
end)

EmoteRemote.OnServerEvent:Connect(function(player, idx)
	local f = player.Character and fighters[player.Character]
	if not f or f.dead or type(idx) ~= "number" then return end
	if idx == 0 then
		if f.actionKind == "emote" then f:clear() end
	elseif not f.action then
		local clip = Config.Emotes[idx] or Config.PowerEmotes[idx - #Config.Emotes]
		if clip and f.anim:HasClip(clip) then f:play(clip, 0.25, "emote") end
	end
end)

-- enemies, waves, scoring ---------------------------------------------------------------------------------------------
local skinCount = {}
local function spawnEnemy(arch: string, i: number, at: CFrame?)
	local spec = GameData.Enemies[arch]
	local ai = Config.Enemies[arch]
	local cfg = Config.Models[spec.model]
	local template = cfg and ServerStorage.SPSO.Characters:FindFirstChild(cfg.template)
	if not template then
		warn("[SPSO] no template for enemy model " .. tostring(spec.model))
		return
	end
	local e = template:Clone()
	e.Name = spec.displayName
	if #ai.skins > 0 then -- optional costume recolours
		skinCount[arch] = (skinCount[arch] or 0) + 1
		local skin = ai.skins[(skinCount[arch] - 1) % #ai.skins + 1]
		e:SetAttribute("SPSO_Variant", skin)
		local body = e:FindFirstChild(cfg.bodyPart, true)
		local head = e:FindFirstChild(cfg.headPart, true)
		local b, h = Assets.Skins[spec.model .. "_" .. skin .. "_Body"], Assets.Skins[spec.model .. "_" .. skin .. "_Head"]
		if body and b and b ~= "" then body.TextureID = b end
		if head and h and h ~= "" then head.TextureID = h end
	end
	local hum = e:FindFirstChildOfClass("Humanoid")
	hum.MaxHealth, hum.Health = spec.health, spec.health
	hum.BreakJointsOnDeath = false
	hum.WalkSpeed = spec.speed
	hum.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
	e:PivotTo(at or (spawnPoint("Enemy", i) + Vector3.new(math.random() * 4 - 2, 3, math.random() * 4 - 2)))
	e.Parent = enemyFolder
	e.HumanoidRootPart:SetNetworkOwner(nil)
	local f = Fighter.new(e, "Enemy", nil, spec.model, arch)
	f.nextAttack = now() + 1.2 + math.random() * 1.5
	if ai.boss then e:SetAttribute("SPSO_Boss", true) end
	hum.Died:Connect(function() f:die(nil, nil) end)
	FxRemote:FireAllClients("spawn", { model = e })
	return f
end

local function banner(text: string)
	SPSO:SetAttribute("Banner", text)
	SPSO:SetAttribute("BannerSeq", (SPSO:GetAttribute("BannerSeq") or 0) + 1)
end

local function heroAlive(): boolean
	for _, f in fighters do
		if f.team == "Hero" and not f.dead and inBrawler(f) then return true end
	end
	return false
end

-- medal thresholds: the original ScoreCalculator over this run's waves, for the current player count
local function medals(playerCount: number)
	playerCount = math.max(1, playerCount)
	local num2, num3, combo = 0, 0, 0
	for _, wave in Config.Waves do
		for arch, n in wave.enemies do
			local spec = GameData.Enemies[arch]
			for _ = 1, n do
				combo = math.min(combo + spec.health / (40 * playerCount), 2.99)
				local ko = S.koValues[math.clamp(spec.rank or 1, 0, 5) + 1]
				num2 += ko
				num3 += ko * math.floor(combo)
			end
		end
		combo = math.max(0, combo - S.comboSpawnerLoss)
	end
	local num4 = (num2 + num3) * ((S.survivalBonus[1] or 1) - 1)
	local num14 = num3 + num4
	return { silver = math.floor(num2 + num14 * S.medalRatios.silver), gold = math.floor(num2 + num14 * S.medalRatios.gold),
		adamantium = math.floor(num2 + num14 * S.medalRatios.adamantium) }
end

if not Config.Mission then task.spawn(function()
	SPSO:SetAttribute("Waves", #Config.Waves)
	while true do
		SPSO:SetAttribute("State", "waiting")
		repeat task.wait(1) until heroAlive()
		Score.team, Score.deaths, Score.kos = 0, 0, 0
		publishScore()
		local m = medals(#Players:GetPlayers())
		SPSO:SetAttribute("MedalSilver", m.silver)
		SPSO:SetAttribute("MedalGold", m.gold)
		SPSO:SetAttribute("MedalAdamantium", m.adamantium)
		SPSO:SetAttribute("State", "playing")
		local start = now()
		local first = RunService:IsStudio() and SPSO:GetAttribute("TestStartWave") or 1
		for w, wave in Config.Waves do
			if w < first then continue end
			SPSO:SetAttribute("Wave", w)
			SPSO:SetAttribute("Music", wave.music)
			banner(wave.boss and "BOSS FIGHT!" or ("WAVE " .. w))
			task.wait(2.5)
			local i = 0
			for _, arch in { "Thug", "Blaster", "Grenadier", "Bazooka", "Warlord" } do
				for _ = 1, wave.enemies[arch] or 0 do
					i += 1
					spawnEnemy(arch, i + w)
					task.wait(0.35)
				end
			end
			SPSO:SetAttribute("EnemiesLeft", enemiesLeft())
			repeat task.wait(0.5) until enemiesLeft() == 0
			task.wait(Config.WaveBreak)
		end
		publishScore()
		local final = SPSO:GetAttribute("TeamScore") or 0
		local medal = final >= m.adamantium and "Adamantium" or final >= m.gold and "Gold" or final >= m.silver and "Silver" or "Bronze"
		SPSO:SetAttribute("Medal", medal)
		SPSO:SetAttribute("RunTime", math.floor(now() - start))
		SPSO:SetAttribute("KOs", Score.kos)
		SPSO:SetAttribute("State", "results")
		banner("VICTORY!")
		for _, f in fighters do
			if f.team == "Hero" and not f.dead and not f.action and f.anim:HasClip("emote_victory") then
				f:play("emote_victory", 0.25, "emote")
			end
		end
		task.wait(Config.ResultsTime)
		for _, f in fighters do
			if f.team == "Hero" and not f.dead then f.hum.Health = f.hum.MaxHealth end
		end
		if Config.Mode == "Hub" and _G.SPSO_Travel then -- mission over: back to the social zone
			for _, p in Players:GetPlayers() do
				if p:GetAttribute("SPSO_Zone") == "Brawler" then _G.SPSO_Travel(p, Config.StartZone) end
			end
		end
	end
end) end
