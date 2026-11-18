-- Client-side animation for one fighter (player hero or enemy): an ExactAnimator plus
--   * locomotion picked from the character's motion (idle / run with speed scaling / jump up / fall / land),
--     the way the original CharacterMotionController + BehaviorMovement chose clips
--   * actions replicated by the server in the "SPSO_Action" attribute ("clip|serverTime|fade|seq"):
--     attacks, hit reactions, emotes, death; "none" ends the action
--   * root motion of actions applied to the local player's own character (the server moves enemies)
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local HeroPack = require(SPSO:WaitForChild("Runtime"):WaitForChild("HeroPack"))
local ExactAnimator = require(SPSO.Runtime:WaitForChild("ExactAnimator"))
local Config = require(SPSO:WaitForChild("Game"):WaitForChild("GameConfig"))

local CharacterAnimator = {}
CharacterAnimator.__index = CharacterAnimator

function CharacterAnimator.new(model: Model, opts)
	opts = opts or {}
	local heroName = model:GetAttribute("SPSO_Hero") or Config.PlayerHero
	local cfg = Config.Heroes[heroName] or Config.Heroes[Config.PlayerHero]
	local self = setmetatable({}, CharacterAnimator)
	self.model, self.cfg, self.isLocal = model, cfg, opts.isLocal == true
	self.humanoid = model:FindFirstChildOfClass("Humanoid")
	self.hrp = model:FindFirstChild("HumanoidRootPart")
	self.anim = ExactAnimator.new(HeroPack.get(cfg.pack), model, {
		wrapModes = cfg.wrapModes,
		faceTextures = opts.faces ~= false and cfg.faceTextures or nil,
		headPart = cfg.headPart,
		skin = opts.skin ~= false,
		prebuildSkin = opts.prebuildSkin,
		lodDistance = opts.lodDistance or 120,
	})
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
end

function CharacterAnimator:_loco(name: string, fade: number)
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
					if st.time >= st.length then self:_loco("jump_fall_loop", 0.2) end
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
	if horiz > 2.5 then
		self:_loco("movement_run", 0.2)
		anim:GetState("movement_run").speed = math.clamp(horiz / self.cfg.runAnimSpeed, 0.5, 1.6)
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
	self.anim:Destroy()
end

return CharacterAnimator
