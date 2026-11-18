-- SPSO brawler server: heroes and enemies as "fighters", the original attack chains and hit windows
-- (timed by the clips' own AnimationEvents through headless ExactAnimators), hit reactions,
-- enemy AI, waves, power meter. Clients animate every fighter from the replicated "SPSO_Action".
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local ServerStorage = game:GetService("ServerStorage")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Config = require(SPSO:WaitForChild("Game"):WaitForChild("GameConfig"))
local Net = require(SPSO.Game:WaitForChild("Net"))
local HeroPack = require(SPSO:WaitForChild("Runtime"):WaitForChild("HeroPack"))
local ExactAnimator = require(SPSO.Runtime:WaitForChild("ExactAnimator"))

local AttackRemote, EmoteRemote, FxRemote = Net.event("Attack"), Net.event("Emote"), Net.event("Fx")
local heroCfg = Config.Heroes[Config.PlayerHero]
local pack = HeroPack.get(heroCfg.pack)
Players.RespawnTime = Config.RespawnTime

local arena = workspace:WaitForChild(Config.Map, 30)
local spawns = arena and arena:FindFirstChild("Spawns")
local enemyFolder = workspace:FindFirstChild("SPSO_Enemies") or Instance.new("Folder")
enemyFolder.Name = "SPSO_Enemies"
enemyFolder.Parent = workspace

local fighters = {}
local seq = 0
local now = os.clock

local function flat(v: Vector3): Vector3
	return Vector3.new(v.X, 0, v.Z)
end

local function spawnPoint(prefix: string, i: number): CFrame
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

local Fighter = {}
Fighter.__index = Fighter

function Fighter.new(model: Model, team: string, player: Player?)
	local f = setmetatable({}, Fighter)
	f.model, f.team, f.player = model, team, player
	f.hum = model:FindFirstChildOfClass("Humanoid")
	f.hrp = model:FindFirstChild("HumanoidRootPart")
	f.power = 0
	f.chainKind, f.chainIndex, f.chainOpen, f.buffered, f.rIndex = nil, 0, false, nil, 0
	f.hitOpen, f.hitSet = false, {}
	f.action, f.actionKind = nil, nil
	f.dead = false
	f.nextThink, f.nextAttack, f.launchAt = 0, now() + 1.5, nil
	f.actionStart, f.stunImmuneUntil, f.lastHitAt = 0, 0, 0
	f.anim = ExactAnimator.new(pack, nil, { headless = true, wrapModes = heroCfg.wrapModes })
	f.anim.Event:Connect(function(fn, data, clip) f:onEvent(fn, data, clip) end)
	model:SetAttribute("SPSO_Hero", heroCfg.pack)
	model:SetAttribute("SPSO_Team", team)
	model:SetAttribute("SPSO_Dead", false)
	model:SetAttribute("SPSO_Lock", false)
	CollectionService:AddTag(model, "SPSO_Fighter")
	fighters[model] = f
	return f
end

function Fighter:play(clip: string, fade: number, kind: string)
	seq += 1
	local anim = self.anim
	if anim:IsPlaying(clip) then anim:Stop(clip) end
	anim:CrossFade(clip, fade)
	self.action, self.actionKind = clip, kind
	self.actionStart = now()
	self.hitOpen, self.chainOpen, self.hitSet = false, false, {}
	self.model:SetAttribute("SPSO_Action", string.format("%s|%.4f|%.3f|%d", clip, workspace:GetServerTimeNow(), fade, seq))
	self.model:SetAttribute("SPSO_Lock", kind ~= "emote")
end

function Fighter:clear()
	seq += 1
	self.action, self.actionKind = nil, nil
	self.chainKind, self.chainIndex, self.chainOpen = nil, 0, false
	self.hitOpen, self.launchAt = false, nil
	self.anim:Stop()
	self.model:SetAttribute("SPSO_Action", string.format("none|%.4f|0.2|%d", workspace:GetServerTimeNow(), seq))
	self.model:SetAttribute("SPSO_Lock", false)
end

function Fighter:addPower(n: number)
	self.power = math.clamp(self.power + n, 0, Config.SuperCost)
	if self.player then self.player:SetAttribute("SPSO_Power", self.power) end
end

function Fighter:onEvent(fn: string, _data: string, clip: string)
	if clip ~= self.action then return end
	if fn == "OnCollisionEnableAnimTag" then
		self.hitOpen, self.hitSet = true, {}
	elseif fn == "OnCollisionDisableAnimTag" then
		self.hitOpen = false
	elseif fn == "OnChainAttackAnimTag" and not self.chainOpen then
		self.chainOpen = true
		if self.buffered then
			local k = self.buffered
			self.buffered = nil
			self:tryAttack(k)
		end
	end
end

function Fighter:tryAttack(kind: string)
	if self.dead or self.actionKind == "death" then return end
	if self.actionKind == "recoil" then
		-- heroes can fight out of a small/big recoil (not out of a launch)
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
	if kind == "Super" then
		if self.team == "Hero" and self.power < Config.SuperCost then return end
		self:addPower(-Config.SuperCost)
		self.chainKind, self.chainIndex = "Super", 1
		self:play(Config.Chains.Super[1], Config.FadeAttack, "attack")
		return
	end
	local chain = Config.Chains[kind]
	if not chain then return end
	local idx
	if kind == "R" then
		self.rIndex = self.rIndex % #chain + 1
		idx = self.rIndex
	elseif busy and self.chainKind == "L" then
		idx = self.chainIndex + 1
	else
		idx = 1
	end
	if not chain[idx] then return end
	self.chainKind, self.chainIndex = kind, idx
	self:play(chain[idx], Config.FadeAttack, "attack")
end

local function knockback(target, attacker, back: number, up: number)
	if target.team ~= "Enemy" or not target.hrp then return end
	local dir = attacker and attacker.hrp and flat(target.hrp.Position - attacker.hrp.Position) or Vector3.zero
	dir = dir.Magnitude > 0.1 and dir.Unit or -target.hrp.CFrame.LookVector
	target.hum:ChangeState(Enum.HumanoidStateType.Freefall)
	target.hrp.AssemblyLinearVelocity = dir * back + Vector3.new(0, up, 0)
end

local function enemiesLeft(): number
	local n = 0
	for _, f in fighters do
		if f.team == "Enemy" and not f.dead then n += 1 end
	end
	return n
end

function Fighter:die(attacker, data)
	if self.dead then return end
	self.dead = true
	self.buffered = nil
	self.model:SetAttribute("SPSO_Dead", true)
	if self.team == "Enemy" then
		SPSO:SetAttribute("EnemiesLeft", enemiesLeft())
		if data and data.reaction == "launch" then
			knockback(self, attacker, 30, 42)
			self:play("recoil_launch", Config.FadeRecoil, "death")
			task.delay(0.75, function()
				if self.model.Parent then self:play("recoil_launch_land", 0.05, "death") end
			end)
		else
			self:play("recoil_death", Config.FadeRecoil, "death")
		end
		task.delay(Config.Enemy.despawnAfter, function()
			fighters[self.model] = nil
			self.model:Destroy()
		end)
	else
		self:play("recoil_death", Config.FadeRecoil, "death")
		if self.hrp then self.hrp.Anchored = true end
	end
end

function Fighter:takeHit(attacker, data)
	if self.dead then return end
	local dmg = data.damage * (attacker.team == "Enemy" and Config.Enemy.damageScale or 1)
	self.hum.Health = math.max(0, self.hum.Health - dmg)
	if attacker.team == "Hero" then attacker:addPower(Config.PowerPerHit) end
	FxRemote:FireAllClients("hit", {
		pos = self.hrp.Position + Vector3.new(0, 4, 0), amount = math.floor(dmg + 0.5),
		heavy = data.reaction ~= "small", team = self.team,
	})
	if self.team == "Enemy" and attacker.hrp then
		local dir = flat(attacker.hrp.Position - self.hrp.Position)
		if dir.Magnitude > 0.1 then self.hrp.CFrame = CFrame.lookAt(self.hrp.Position, self.hrp.Position + dir) end
	end
	if self.hum.Health <= 0 then
		self:die(attacker, data)
		return
	end
	self.lastHitAt = now()
	if self.team == "Hero" then
		if now() < self.stunImmuneUntil then return end -- damage only while recovering
		self.stunImmuneUntil = now() + Config.HeroStunImmunity
	end
	self.buffered = nil
	local reaction = data.reaction
	if self.team == "Hero" and reaction == "launch" then reaction = "big" end
	if reaction == "launch" then
		self:play("recoil_launch", Config.FadeRecoil, "recoil")
		self.launchAt = now()
		knockback(self, attacker, 26, 38)
	else
		self:play(reaction == "big" and "recoil_big" or "recoil_small", Config.FadeRecoil, "recoil")
	end
	if self.team == "Enemy" then self.nextAttack = math.max(self.nextAttack, now() + 0.9) end
end

function Fighter:checkHits()
	local data = Config.Attacks[self.action]
	if not data or not self.hrp then return end
	local pos, look = self.hrp.Position, flat(self.hrp.CFrame.LookVector).Unit
	local cosArc = math.cos(math.rad(Config.Arc / 2))
	for _, t in fighters do
		if t ~= self and t.team ~= self.team and not t.dead and not self.hitSet[t] and t.hrp and t.hrp.Parent then
			local off = flat(t.hrp.Position - pos)
			local dist = off.Magnitude
			local hit
			if data.radius then
				hit = dist <= data.radius + Config.TargetRadius
			else
				hit = dist <= Config.Reach + Config.TargetRadius and (dist < 3 or look:Dot(off.Unit) >= cosArc)
			end
			if hit and math.abs(t.hrp.Position.Y - pos.Y) < 9 then
				self.hitSet[t] = true
				t:takeHit(self, data)
			end
		end
	end
end

function Fighter:onActionEnd()
	local clip, kind = self.action, self.actionKind
	if kind == "death" then return end
	if clip == "recoil_launch_land" then
		self:play("recoil_getup", 0.1, "recoil")
		return
	end
	local b = self.buffered
	self.buffered = nil
	self:clear()
	if b then self:tryAttack(b) end
end

function Fighter:think()
	local t = now()
	if self.dead or t < self.nextThink then return end
	self.nextThink = t + Config.Enemy.thinkRate
	if self.action then
		self.hum.WalkSpeed = 0
		return
	end
	self.hum.WalkSpeed = Config.Enemy.walkSpeed
	local best, bd
	for _, o in fighters do
		if o.team == "Hero" and not o.dead and o.hrp and o.hrp.Parent then
			local d = flat(o.hrp.Position - self.hrp.Position).Magnitude
			if not bd or d < bd then best, bd = o, d end
		end
	end
	if not best then
		self.hum:Move(Vector3.zero)
		return
	end
	local dir = flat(best.hrp.Position - self.hrp.Position)
	if bd > Config.Enemy.attackRange then
		-- keep a little spacing between enemies
		local push = Vector3.zero
		for _, o in fighters do
			if o ~= self and o.team == "Enemy" and not o.dead and o.hrp then
				local away = flat(self.hrp.Position - o.hrp.Position)
				if away.Magnitude < 6 and away.Magnitude > 0.01 then push += away.Unit * (6 - away.Magnitude) end
			end
		end
		self.hum:MoveTo(best.hrp.Position - dir.Unit * (Config.Enemy.attackRange * 0.7) + push)
	else
		self.hum:Move(Vector3.zero)
		self.hrp.CFrame = CFrame.lookAt(self.hrp.Position, self.hrp.Position + dir)
		local swinging = 0
		for _, o in fighters do
			if o.team == "Enemy" and o.actionKind == "attack" then swinging += 1 end
		end
		if t >= self.nextAttack and swinging < Config.Enemy.maxAttackers and t - best.lastHitAt > Config.Enemy.waitAfterHeroHit then
			local list = Config.Enemy.attacks
			self:play(list[math.random(#list)], Config.FadeAttack, "attack")
			local c = Config.Enemy.cooldown
			self.nextAttack = t + c[1] + math.random() * (c[2] - c[1])
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
			local clip = pack.clips[f.action]
			if clip and clip.rootMotion then f.hrp.CFrame += f.hrp.CFrame.LookVector * d end
		end
		if f.action == "recoil_launch" and f.launchAt and not f.dead and now() - f.launchAt > 0.75 then
			f.launchAt = nil
			f:play("recoil_launch_land", 0.05, "recoil")
		elseif f.action and not f.anim:IsPlaying(f.action) then
			f:onActionEnd()
		end
		if f.hitOpen then f:checkHits() end
		if f.team == "Enemy" then f:think() end
	end
end)

-- players ---------------------------------------------------------------------------------------------
local function setupCharacter(player: Player, char: Model)
	local hum = char:WaitForChild("Humanoid") :: Humanoid
	char:WaitForChild("HumanoidRootPart")
	hum.MaxHealth, hum.Health = heroCfg.health, heroCfg.health
	hum.BreakJointsOnDeath = false
	hum.WalkSpeed = heroCfg.walkSpeed
	hum.UseJumpPower = true
	hum.JumpPower = heroCfg.jumpPower
	char:PivotTo(spawnPoint("Player", player.UserId % 4 + 1) + Vector3.new(0, 4, 0))
	local f = Fighter.new(char, "Hero", player)
	f.power = player:GetAttribute("SPSO_Power") or 0
	hum.Died:Connect(function() f:die(nil, nil) end)
end

local function onPlayer(player: Player)
	player:SetAttribute("SPSO_Power", player:GetAttribute("SPSO_Power") or 0)
	player.CharacterAdded:Connect(function(c) setupCharacter(player, c) end)
	if player.Character then setupCharacter(player, player.Character) end
end
Players.PlayerAdded:Connect(onPlayer)
for _, p in Players:GetPlayers() do task.spawn(onPlayer, p) end

AttackRemote.OnServerEvent:Connect(function(player, kind)
	local f = player.Character and fighters[player.Character]
	if f and (kind == "L" or kind == "R" or kind == "Super") then f:tryAttack(kind) end
end)

EmoteRemote.OnServerEvent:Connect(function(player, idx)
	local f = player.Character and fighters[player.Character]
	if not f or f.dead or type(idx) ~= "number" then return end
	if idx == 0 then
		if f.actionKind == "emote" then f:clear() end
	elseif not f.action and Config.Emotes[idx] then
		f:play(Config.Emotes[idx], 0.25, "emote")
	end
end)

-- enemies and waves ---------------------------------------------------------------------------------
local function spawnEnemy(i: number)
	local template = ServerStorage.SPSO.Characters:FindFirstChild("Enemy_Luchador")
	if not template then return end
	local e = template:Clone()
	local variant = Config.Variants[(i - 1) % #Config.Variants + 1]
	e.Name = Config.Enemy.name .. " " .. variant.name
	e:SetAttribute("SPSO_Variant", variant.name)
	local hum = e:FindFirstChildOfClass("Humanoid")
	hum.MaxHealth, hum.Health = Config.Enemy.health, Config.Enemy.health
	hum.BreakJointsOnDeath = false
	hum.WalkSpeed = Config.Enemy.walkSpeed
	hum.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
	e:PivotTo(spawnPoint("Enemy", i) + Vector3.new(math.random() * 4 - 2, 4, math.random() * 4 - 2))
	e.Parent = enemyFolder
	e.HumanoidRootPart:SetNetworkOwner(nil)
	local f = Fighter.new(e, "Enemy", nil)
	f.nextAttack = now() + 1.2 + math.random() * 1.5
	hum.Died:Connect(function() f:die(nil, nil) end)
end

local function banner(text: string)
	SPSO:SetAttribute("Banner", text)
	SPSO:SetAttribute("BannerSeq", (SPSO:GetAttribute("BannerSeq") or 0) + 1)
end

local function heroAlive(): boolean
	for _, f in fighters do
		if f.team == "Hero" and not f.dead then return true end
	end
	return false
end

task.spawn(function()
	SPSO:SetAttribute("Waves", #Config.Waves)
	while true do
		repeat task.wait(1) until heroAlive()
		for w, count in Config.Waves do
			SPSO:SetAttribute("Wave", w)
			banner("WAVE " .. w)
			task.wait(2.5)
			for i = 1, count do
				spawnEnemy(i + w)
				task.wait(0.35)
			end
			SPSO:SetAttribute("EnemiesLeft", enemiesLeft())
			repeat task.wait(0.5) until enemiesLeft() == 0
			task.wait(Config.WaveBreak)
		end
		banner("VICTORY!")
		for _, f in fighters do
			if f.team == "Hero" and not f.dead and not f.action then f:play("emote_victory", 0.25, "emote") end
		end
		task.wait(8)
		for _, f in fighters do
			if f.team == "Hero" and not f.dead then f.hum.Health = f.hum.MaxHealth end
		end
	end
end)
