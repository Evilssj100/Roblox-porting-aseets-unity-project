-- Client-side animation for one fighter (player hero or enemy): an ExactAnimator plus
--   * locomotion picked from the character's motion (idle / run with speed scaling / jump up / fall / land),
--     the way the original CharacterMotionController + BehaviorMovement chose clips
--   * actions replicated by the server in the "SPSO_Action" attribute ("clip|serverTime|fade|seq"):
--     attacks, hit reactions, emotes, death; "none" ends the action
--   * the original effect sequences for each action (attack effects, power emotes, hurt, death) via FxPlayer
--   * root motion of actions applied to the local player's own character (the server moves enemies)
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local HeroPack = require(SPSO:WaitForChild("Runtime"):WaitForChild("HeroPack"))
local ExactAnimator = require(SPSO.Runtime:WaitForChild("ExactAnimator"))
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local GameData = require(Game:WaitForChild("GameData"))
local FxPlayer = require(Game:WaitForChild("FxPlayer"))

local CharacterAnimator = {}
CharacterAnimator.__index = CharacterAnimator

-- clip -> effect sequence names for a fighter's data (hero or enemy archetype)
local effectCache = {}
local function effectsFor(dataKey: string, data, fxHero: string)
	if effectCache[dataKey] then return effectCache[dataKey] end
	local map = {}
	local function add(clip, name)
		if not name then return end
		map[clip] = map[clip] or {}
		for _, n in { name, (string.gsub(name, "_Snd_sequence$", "sequence")), (string.gsub(name, "_audio_sequence$", "sequence")) } do
			if FxPlayer.has(fxHero, n) and not table.find(map[clip], n) then table.insert(map[clip], n) end
		end
	end
	for _, a in data.attacks or {} do add(a.anim, a.effect) end
	for i = 1, 3 do add("power_emote_" .. i, "Power Emote " .. i) end
	if dataKey ~= fxHero then -- enemy archetypes: their effects live in the shared character fx bundle
		for _, a in data.attacks or {} do
			if a.effect and FxPlayer.has("Shared", a.effect) then
				map[a.anim] = map[a.anim] or {}
				table.insert(map[a.anim], "Shared/" .. a.effect)
			end
		end
		if FxPlayer.has("Shared", "death_effect_sequence") then map.recoil_death = { "Shared/death_effect_sequence" } end
		if FxPlayer.has("Shared", "recoil_launch_sequence") then map.recoil_launch = { "Shared/recoil_launch_sequence" } end
	end
	local seqs = require(Game.FxData).Heroes[fxHero]
	if seqs then
		for name in seqs.sequences do
			local l = string.lower(name)
			if string.find(l, "hurt") then add("recoil_small", name); add("recoil_big", name) end
			if string.find(l, "death") then add("recoil_death", name) end
		end
	end
	effectCache[dataKey] = map
	return map
end

function CharacterAnimator.new(model: Model, opts)
	opts = opts or {}
	local heroName = model:GetAttribute("SPSO_Hero") or Config.DefaultHero
	local cfg = Config.Models[heroName] or Config.Models[Config.DefaultHero]
	local archetype = model:GetAttribute("SPSO_Archetype")
	local data = archetype and GameData.Enemies[archetype] or GameData.Heroes[heroName] or {}
	local self = setmetatable({}, CharacterAnimator)
	self.model, self.cfg, self.isLocal, self.hero = model, cfg, opts.isLocal == true, heroName
	self.humanoid = model:FindFirstChildOfClass("Humanoid")
	self.hrp = model:FindFirstChild("HumanoidRootPart")
	local facesList = nil
	if opts.faces ~= false and cfg.faceTextures then
		facesList = table.clone(cfg.faceTextures)
		if facesList[1] == "" or facesList[1] == nil then
			local head = model:FindFirstChild(cfg.headPart, true)
			facesList[1] = head and head.TextureID or ""
		end
		for i = 2, 8 do
			if facesList[i] == "" then facesList[i] = facesList[1] end
		end
	end
	self.anim = ExactAnimator.new(HeroPack.get(cfg.pack), model, {
		wrapModes = cfg.wrapModes,
		faceTextures = facesList,
		headPart = cfg.headPart,
		skin = opts.skin ~= false,
		prebuildSkin = opts.prebuildSkin,
		lodDistance = opts.lodDistance or 120,
	})
	self.effects = effectsFor((archetype or heroName), data, heroName)
	self.fx = nil
	self.action, self.actionSeq, self.loco = nil, nil, nil
	self.airTime, self.landLock = 0, 0
	local params = RaycastParams.new()
	params.FilterType = Enum.RaycastFilterType.Exclude
	params.FilterDescendantsInstances = { model }
	params.IgnoreWater = true
	self.rayParams = params
	self:_loco("movement_idle", 0)
	self.conns = {
		model:GetAttributeChangedSignal("SPSO_Action"):Connect(function() self:_onAction() end),
	}
	self:_onAction()
	return self
end

function CharacterAnimator:_onAction()
	local s = self.model:GetAttribute("SPSO_Action")
	if type(s) ~= "string" then return end
	local clip, t0, fade, seq = string.match(s, "^([^|]+)|([^|]+)|([^|]+)|([^|]+)$")
	if not clip or seq == self.actionSeq then return end
	self.actionSeq = seq
	if self.fx then
		for _, h in self.fx do h.stop() end
		self.fx = nil
	end
	if clip == "none" then
		self.action = nil
		return
	end
	local anim = self.anim
	if not anim:HasClip(clip) then return end
	if anim:IsPlaying(clip) then anim:Stop(clip) end
	anim:CrossFade(clip, tonumber(fade) or 0.1)
	local late = workspace:GetServerTimeNow() - (tonumber(t0) or 0)
	if late > 0 and late < 0.3 then anim:GetState(clip).time = late end
	self.action, self.loco = clip, nil
	local names = self.effects[clip]
	if names and late < 1 then
		self.fx = {}
		for _, n in names do
			local src, seqName = string.match(n, "^(%w+)/(.+)$")
			local h = FxPlayer.play(src or self.hero, seqName or n, self.model)
			if h then table.insert(self.fx, h) end
		end
	end
end

function CharacterAnimator:_loco(name: string, fade: number)
	if not self.remap then
		self.remap = {}
		for _, base in { "movement_idle", "movement_run", "movement_walk" } do
			if not self.anim:HasClip(base) and self.anim:HasClip(base .. "_sidekick") then self.remap[base] = base .. "_sidekick" end
		end
	end
	name = self.remap[name] or name
	if not self.anim:HasClip(name) then return end -- civilians and pigeons have no jump set: keep the current clip
	if self.loco == name and self.anim:IsPlaying(name) then return end
	self.loco = name
	self.anim:CrossFade(name, fade)
end

function CharacterAnimator:_locomotion(dt: number)
	local hrp, hum, anim = self.hrp, self.humanoid, self.anim
	local v = hrp.AssemblyLinearVelocity
	local horiz = math.sqrt(v.X * v.X + v.Z * v.Z)
	local grounded
	if self.isLocal and hum then
		grounded = hum.FloorMaterial ~= Enum.Material.Air
	else
		local depth = hrp.Size.Y / 2 + (hum and hum.HipHeight or 2) + 0.7
		grounded = workspace:Raycast(hrp.Position, Vector3.new(0, -depth, 0), self.rayParams) ~= nil
	end
	if not grounded then
		self.airTime += dt
		if self.airTime > 0.12 then
			if v.Y > 1 then
				if self.loco ~= "jump_up" and self.loco ~= "jump_run_up" then
					self:_loco(horiz > 6 and "jump_run_up" or "jump_up", 0.1)
				end
			else
				local cur = self.loco
				if cur == "jump_fall" or cur == "jump_run_fall" then
					local st = anim:GetState(cur)
					if not st or st.time >= st.length then self:_loco("jump_fall_loop", 0.2) end
				elseif cur ~= "jump_fall_loop" then
					self:_loco(horiz > 6 and "jump_run_fall" or "jump_fall", 0.2)
				end
			end
		end
		return
	end
	if self.airTime > 0.3 then
		self:_loco(horiz > 6 and "jump_run_land" or "jump_land", 0.08)
		self.landLock = 0.22
	end
	self.airTime = 0
	if self.landLock > 0 then
		self.landLock -= dt
		return
	end
	if horiz > 2.5 and self.model:GetAttribute("SPSO_Walk") and anim:HasClip("movement_walk") then
		self:_loco("movement_walk", 0.25)
	elseif horiz > 2.5 then
		self:_loco("movement_run", 0.2)
		local st = anim:GetState(self.loco)
		if st then st.speed = math.clamp(horiz / self.cfg.runAnimSpeed, 0.5, 1.6) end
	else
		self:_loco("movement_idle", 0.3)
	end
end

function CharacterAnimator:Update(dt: number)
	local hrp = self.hrp
	if not hrp or not hrp.Parent then return end
	local anim = self.anim
	if self.action then
		local st = anim:GetState(self.action)
		if not st.enabled then
			self.action = nil -- a Once clip finished; ClampForever actions hold until the server ends them
		end
	end
	if not self.action and not self.model:GetAttribute("SPSO_Dead") then
		self:_locomotion(dt)
	end
	anim:Step(dt)
	local d = anim:ConsumeRootMotion()
	if self.isLocal and self.action and d ~= 0 then
		local clip = anim.pack.clips[self.action]
		if clip and clip.rootMotion then hrp.CFrame += hrp.CFrame.LookVector * d end
	end
end

function CharacterAnimator:Current(): string?
	return self.action
end

function CharacterAnimator:Destroy()
	for _, c in self.conns do c:Disconnect() end
	if self.fx then
		for _, h in self.fx do h.stop() end
	end
	FxPlayer.clear(self.model)
	self.anim:Destroy()
end

return CharacterAnimator
