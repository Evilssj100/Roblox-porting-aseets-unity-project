-- SPSO brawler client: loading screen, hero select (live animated previews), the exact animation runtime for
-- every fighter, the original effect sequences and sounds, the brawler camera, input (L chain, R1-R3 power
-- attacks, super, emotes), the HUD (built from the original GUI art), projectiles, beams, pickups, results.
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local ContextActionService = game:GetService("ContextActionService")
local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local ContentProvider = game:GetService("ContentProvider")
local Debris = game:GetService("Debris")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local GameData = require(Game:WaitForChild("GameData"))
local Assets = require(Game:WaitForChild("Assets"))
local Net = require(Game:WaitForChild("Net"))
local Sound = require(Game:WaitForChild("Sound"))
local FxPlayer = require(Game:WaitForChild("FxPlayer"))
local CharacterAnimator = require(Game:WaitForChild("CharacterAnimator"))
local HeroPack = require(SPSO:WaitForChild("Runtime"):WaitForChild("HeroPack"))
local ExactAnimator = require(SPSO.Runtime:WaitForChild("ExactAnimator"))

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")
local AttackRemote, EmoteRemote, FxRemote = Net.event("Attack"), Net.event("Emote"), Net.event("Fx")
local SelectRemote = Net.event("SelectHero")
local G = Assets.Gui
local HEADING, BODY = Enum.Font.Bangers, Enum.Font.FredokaOne

local function img(parent, key, props)
	local i = Instance.new("ImageLabel")
	i.BackgroundTransparency = 1
	i.Image = G[key] or ""
	for k, v in props or {} do i[k] = v end
	i.Parent = parent
	return i
end

local function text(parent, str, props)
	local l = Instance.new("TextLabel")
	l.BackgroundTransparency = 1
	l.Font = BODY
	l.Text = str
	l.TextColor3 = Color3.new(1, 1, 1)
	l.TextStrokeTransparency = 0.35
	l.TextScaled = false
	for k, v in props or {} do l[k] = v end
	l.Parent = parent
	return l
end

local function screen(name, order)
	local g = Instance.new("ScreenGui")
	g.Name = name
	g.ResetOnSpawn = false
	g.IgnoreGuiInset = true
	g.DisplayOrder = order or 0
	g.ZIndexBehavior = Enum.ZIndexBehavior.Sibling
	g.Parent = playerGui
	return g
end

-- fighters -------------------------------------------------------------------------------------------------------------
local animators = {}
local decor = {} -- model -> { health bar, shadow }
FxPlayer.setAnimatorResolver(function(model)
	local ca = animators[model]
	return type(ca) == "table" and ca.anim or nil
end)

local function groundDecal(key, size, color, transparency)
	local p = Instance.new("Part")
	p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch, p.CastShadow = true, false, false, false, false
	p.Transparency = 1
	p.Size = Vector3.new(size, 0.05, size)
	local d = Instance.new("Decal")
	d.Face = Enum.NormalId.Top
	d.Texture = G[key] or ""
	d.Color3 = color or Color3.new(1, 1, 1)
	d.Transparency = transparency or 0
	d.Parent = p
	p.Parent = workspace:FindFirstChild("SPSO_FX") or workspace
	return p, d
end

local function makeHealthBar(model: Model, boss: boolean)
	local hrp = model:FindFirstChild("HumanoidRootPart")
	local bb = Instance.new("BillboardGui")
	bb.Name = "SPSO_Health"
	bb.Size = UDim2.fromOffset(96, 12)
	local ext = model:GetExtentsSize()
	bb.StudsOffset = Vector3.new(0, math.max(4, ext.Y - 2.2), 0)
	bb.AlwaysOnTop = true
	bb.Adornee = hrp
	img(bb, "bh_enemy_health_bg", { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Stretch })
	local damage = img(bb, "bh_enemy_health_damage", { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Stretch, ZIndex = 2 })
	local fill = img(bb, "bh_enemy_health_full", { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Stretch, ZIndex = 3 })
	img(bb, "bh_enemy_health_gleam", { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Stretch, ZIndex = 4 })
	bb.Enabled = not boss -- the boss gets the big bar at the top of the screen
	bb.Parent = playerGui
	return { gui = bb, fill = fill, damage = damage, shown = 1 }
end

local function attach(model: Instance)
	if not model:IsA("Model") or animators[model] then return end
	animators[model] = "pending"
	task.spawn(function()
		local root = model:WaitForChild("RootPart", 10)
		local hrp = model:WaitForChild("HumanoidRootPart", 10)
		if not root or not hrp then
			animators[model] = nil
			return
		end
		local t0 = os.clock()
		while #root:GetDescendants() < 30 and os.clock() - t0 < 10 do task.wait() end
		local isLocal = model == player.Character
		local variant = model:GetAttribute("SPSO_Variant")
		local enemy = model:GetAttribute("SPSO_Team") == "Enemy"
		local ok, ca = pcall(CharacterAnimator.new, model, {
			-- exact bone-scale skinning (EditableMesh) for the local hero; others use the bones (memory budget)
			isLocal = isLocal, skin = isLocal, prebuildSkin = isLocal,
			faces = not (variant and variant ~= ""), lodDistance = 300,
		})
		if not ok then
			warn("[SPSO] animator failed for " .. model:GetFullName() .. ": " .. tostring(ca))
			animators[model] = nil
			return
		end
		if not model.Parent then
			ca:Destroy()
			animators[model] = nil
			return
		end
		animators[model] = ca
		local d = { shadow = (groundDecal(G.ShadowAlpha and "ShadowAlpha" or "Shadow", 6, Color3.new(0, 0, 0), G.ShadowAlpha and 0.25 or 0.8)) }
		if enemy then d.bar = makeHealthBar(model, model:GetAttribute("SPSO_Boss") == true) end
		decor[model] = d
	end)
end

local function detach(model: Instance)
	local ca = animators[model]
	if type(ca) == "table" then ca:Destroy() end
	animators[model] = nil
	local d = decor[model]
	if d then
		if d.bar then d.bar.gui:Destroy() end
		if d.shadow then d.shadow:Destroy() end
	end
	decor[model] = nil
end

CollectionService:GetInstanceAddedSignal("SPSO_Fighter"):Connect(attach)
CollectionService:GetInstanceRemovedSignal("SPSO_Fighter"):Connect(detach)
for _, m in CollectionService:GetTagged("SPSO_Fighter") do attach(m) end

-- target ring under the enemy you are fighting (original enemy-selected ring and arrows)
local ringPart, ringDecal = groundDecal("enemyselected_ring", 7, Color3.fromRGB(255, 255, 255), 0.1)
local arrowPart = groundDecal("enemyselected_arrows", 9, Color3.fromRGB(255, 255, 255), 0.1)
local selfRing = groundDecal("selection_ring", 6.5, Color3.fromRGB(120, 230, 255), 0.45)

-- camera ------------------------------------------------------------------------------------------------------------------
local camera = workspace.CurrentCamera
local zoom, camFocus, shake = 1, nil, 0
FxPlayer.OnShake = function(s) shake = math.max(shake, s) end
UserInputService.InputChanged:Connect(function(input, gp)
	if not gp and input.UserInputType == Enum.UserInputType.MouseWheel then
		zoom = math.clamp(zoom - input.Position.Z * 0.08, Config.Camera.zoomMin, Config.Camera.zoomMax)
	end
end)

local function updateCamera(dt: number)
	local char = player.Character
	local hrp = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp then return end
	camera.CameraType = Enum.CameraType.Scriptable
	local focus = hrp.Position * Vector3.new(1, 0, 1) + Vector3.new(0, hrp.Position.Y - 3.3 + Config.Camera.lookHeight, 0)
	-- keep the camera inside the arena's front wall (the original camera never left the play space)
	local maxZ = Config.Camera.maxCameraZ - Config.Camera.offset.Z * zoom
	if focus.Z > maxZ then focus = Vector3.new(focus.X, focus.Y, maxZ) end
	camFocus = camFocus and camFocus:Lerp(focus, 1 - math.exp(-7 * dt)) or focus
	local jitter = Vector3.zero
	if shake > 0 then
		shake = math.max(0, shake - dt * 2.5)
		jitter = Vector3.new(math.random() - 0.5, math.random() - 0.5, 0) * shake
	end
	camera.FieldOfView = Config.Camera.fov
	camera.CFrame = CFrame.lookAt(camFocus + Config.Camera.offset * zoom + jitter, camFocus + jitter * 0.5)
end

-- local hero: movement lock, knockback, emote cancel --------------------------------------------------------------------
local pushVel, pushUntil = Vector3.zero, 0
local function updateLocal()
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	if not hum then return end
	local cfg = Config.Heroes[char:GetAttribute("SPSO_Hero") or Config.DefaultHero]
	local locked = char:GetAttribute("SPSO_Lock") == true or char:GetAttribute("SPSO_Dead") == true
	hum.WalkSpeed = locked and 0 or cfg.walkSpeed
	hum.UseJumpPower = true
	hum.JumpPower = locked and 0 or cfg.jumpPower
	hum.AutoRotate = not locked
	local hrp = char:FindFirstChild("HumanoidRootPart")
	if hrp and os.clock() < pushUntil then
		local v = hrp.AssemblyLinearVelocity
		hrp.AssemblyLinearVelocity = Vector3.new(pushVel.X, v.Y, pushVel.Z)
	end
	local ca = animators[char]
	if type(ca) == "table" and ca:Current() and (string.sub(ca:Current(), 1, 6) == "emote_" or string.sub(ca:Current(), 1, 12) == "power_emote_")
		and hum.MoveDirection.Magnitude > 0.1 then
		EmoteRemote:FireServer(0)
	end
end

-- input ----------------------------------------------------------------------------------------------------------------------
local targetModel
local function nearestEnemy(maxDist)
	local char = player.Character
	local hrp = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp then return nil end
	local best, bd = nil, maxDist or 22
	for m in animators do
		if m:GetAttribute("SPSO_Team") == "Enemy" and not m:GetAttribute("SPSO_Dead") and m.PrimaryPart then
			local d = (m.PrimaryPart.Position - hrp.Position).Magnitude
			if d < bd then best, bd = m, d end
		end
	end
	return best
end

local function faceTarget()
	local char = player.Character
	local hrp = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp or char:GetAttribute("SPSO_Lock") then return end
	local t = nearestEnemy(18)
	if t then
		local dir = (t.PrimaryPart.Position - hrp.Position) * Vector3.new(1, 0, 1)
		if dir.Magnitude > 0.1 then hrp.CFrame = CFrame.lookAt(hrp.Position, hrp.Position + dir) end
	end
end

local selecting = false
local function attack(kind)
	if selecting or not player.Character then return end
	faceTarget()
	AttackRemote:FireServer(kind)
end

local function bind(name: string, kind: string, title: string, ...)
	ContextActionService:BindAction(name, function(_, state)
		if state == Enum.UserInputState.Begin then attack(kind) end
		return Enum.ContextActionResult.Sink
	end, true, ...)
	ContextActionService:SetTitle(name, title)
end
bind("SPSO_L", "L", "HIT", Enum.UserInputType.MouseButton1, Enum.KeyCode.ButtonX)
bind("SPSO_R1", "R1", "P1", Enum.UserInputType.MouseButton2, Enum.KeyCode.One, Enum.KeyCode.ButtonY)
bind("SPSO_R2", "R2", "P2", Enum.KeyCode.Two, Enum.KeyCode.ButtonL1)
bind("SPSO_R3", "R3", "P3", Enum.KeyCode.Three, Enum.KeyCode.ButtonR1)
bind("SPSO_Super", "Super", "SUPER", Enum.KeyCode.F, Enum.KeyCode.ButtonB)

local showSelect -- defined below
UserInputService.InputBegan:Connect(function(input, gp)
	if gp then return end
	local emoteKeys = { Enum.KeyCode.Four, Enum.KeyCode.Five, Enum.KeyCode.Six, Enum.KeyCode.Seven,
		Enum.KeyCode.Eight, Enum.KeyCode.Nine, Enum.KeyCode.Zero }
	local i = table.find(emoteKeys, input.KeyCode)
	if i and not selecting then EmoteRemote:FireServer(i) end
	if input.KeyCode == Enum.KeyCode.H and showSelect and not selecting then showSelect() end
end)

-- HUD (the original brawler HUD art) ---------------------------------------------------------------------
local hud = screen("SPSO_HUD", 1)
hud.Enabled = false

-- player frame: live portrait of your hero in the ring, life bar, power stars (P1, P2, P3, super)
local frame = img(hud, "bh_playerframe", { Size = UDim2.fromOffset(392, 196), Position = UDim2.fromOffset(8, 4), ZIndex = 2 })
local portraitVp = Instance.new("ViewportFrame")
portraitVp.Size, portraitVp.Position = UDim2.fromOffset(112, 112), UDim2.fromOffset(30, 40)
portraitVp.BackgroundColor3 = Color3.fromRGB(30, 60, 110)
portraitVp.Ambient, portraitVp.LightColor = Color3.fromRGB(180, 180, 190), Color3.new(1, 1, 1)
portraitVp.ZIndex = 1
portraitVp.Parent = frame
Instance.new("UICorner", portraitVp).CornerRadius = UDim.new(1, 0)
local heroName = text(frame, "", { Font = HEADING, TextSize = 26, Size = UDim2.fromOffset(220, 28), Position = UDim2.fromOffset(160, 40),
	TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Color3.fromRGB(255, 244, 200), ZIndex = 4 })
local lifeBg = Instance.new("Frame")
lifeBg.Size, lifeBg.Position = UDim2.fromOffset(212, 22), UDim2.fromOffset(160, 72)
lifeBg.BackgroundColor3 = Color3.fromRGB(20, 26, 50)
lifeBg.ClipsDescendants = true
lifeBg.ZIndex = 3
lifeBg.Parent = frame
Instance.new("UICorner", lifeBg).CornerRadius = UDim.new(0, 8)
local lifeDamage = img(lifeBg, "bh_life_damage", { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Stretch, ZIndex = 3 })
local lifeFill = img(lifeBg, "bh_life_fill", { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Stretch, ZIndex = 4 })
local hpText = text(lifeBg, "", { Size = UDim2.fromScale(1, 1), TextSize = 14, ZIndex = 5 })
local starBox = img(frame, "bh_star_container_4", { Size = UDim2.fromOffset(176, 44), Position = UDim2.fromOffset(160, 100), ZIndex = 3 })
local stars = {}
for i, cost in { 20, 40, 60, 100 } do
	stars[i] = { cost = cost, img = img(starBox, "bh_star_active", { Size = UDim2.fromOffset(36, 36),
		Position = UDim2.fromOffset(6 + (i - 1) * 42, 4), ZIndex = 4 }) }
end
local pwBarBg = Instance.new("Frame")
pwBarBg.Size, pwBarBg.Position = UDim2.fromOffset(176, 6), UDim2.fromOffset(160, 146)
pwBarBg.BackgroundColor3 = Color3.fromRGB(20, 26, 50)
pwBarBg.BorderSizePixel = 0
pwBarBg.ZIndex = 3
pwBarBg.Parent = frame
local pwFill = Instance.new("Frame")
pwFill.Size = UDim2.fromScale(0, 1)
pwFill.BackgroundColor3 = Color3.fromRGB(255, 200, 60)
pwFill.BorderSizePixel = 0
pwFill.ZIndex = 4
pwFill.Parent = pwBarBg

-- power attack buttons (also tappable)
local powerRow = Instance.new("Frame")
powerRow.BackgroundTransparency = 1
powerRow.Size, powerRow.Position = UDim2.fromOffset(330, 74), UDim2.new(0.5, -165, 1, -96)
powerRow.Parent = hud
local layout = Instance.new("UIListLayout", powerRow)
layout.FillDirection = Enum.FillDirection.Horizontal
layout.Padding = UDim.new(0, 10)
layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
local powerButtons = {}
for _, spec in { { "R1", "1", 20 }, { "R2", "2", 40 }, { "R3", "3", 60 }, { "Super", "F", 100 } } do
	local b = Instance.new("ImageButton")
	b.Size = UDim2.fromOffset(spec[1] == "Super" and 86 or 66, 66)
	b.BackgroundTransparency = 1
	b.Image = G.bh_heroup_bubble or G.herobg or ""
	b.Parent = powerRow
	local ring = img(b, "bh_heroup_bubble_flash", { Size = UDim2.fromScale(1, 1) })
	text(b, spec[1] == "Super" and "SUPER" or ("P" .. spec[1]:sub(2)), { Size = UDim2.fromScale(1, 0.5), Position = UDim2.fromScale(0, 0.16),
		Font = HEADING, TextSize = spec[1] == "Super" and 22 or 22 })
	text(b, "[" .. spec[2] .. "] " .. spec[3], { Size = UDim2.fromScale(1, 0.3), Position = UDim2.fromScale(0, 0.6), TextSize = 12 })
	b.Activated:Connect(function() attack(spec[1]) end)
	powerButtons[spec[1]] = { button = b, ring = ring, cost = spec[3] }
end

-- score with the medal you are on track for
local scoreBox = img(hud, "baseWindow", { Size = UDim2.fromOffset(270, 84), Position = UDim2.new(1, -286, 0, 22),
	ScaleType = Enum.ScaleType.Slice, SliceCenter = Rect.new(40, 20, 216, 44) })
local medalIcon = img(scoreBox, "bh_brawler_points_bronze", { Size = UDim2.fromOffset(60, 60), Position = UDim2.fromOffset(-22, 12), ZIndex = 3 })
local scoreText = text(scoreBox, "0", { Font = HEADING, TextSize = 34, Size = UDim2.new(1, -40, 0, 36), Position = UDim2.fromOffset(30, 6),
	TextColor3 = Color3.fromRGB(255, 240, 150) })
local comboText = text(scoreBox, "", { TextSize = 15, Size = UDim2.new(1, -40, 0, 20), Position = UDim2.fromOffset(30, 46) })
local comboFill = Instance.new("Frame")
comboFill.BorderSizePixel = 0
comboFill.BackgroundColor3 = Color3.fromRGB(255, 120, 40)
comboFill.Size, comboFill.Position = UDim2.new(0, 0, 0, 5), UDim2.fromOffset(36, 70)
comboFill.Parent = scoreBox
local waveLabel = text(hud, "", { Font = HEADING, TextSize = 30, Size = UDim2.fromOffset(500, 34), Position = UDim2.new(0.5, -250, 0, 16) })

-- boss bar (original boss frame, life bar and name plate)
local bossBar = Instance.new("Frame")
bossBar.BackgroundTransparency = 1
bossBar.Size, bossBar.Position = UDim2.fromOffset(560, 90), UDim2.new(0.5, -280, 0, 52)
bossBar.Visible = false
bossBar.Parent = hud
img(bossBar, "bh_boss_lifebar_bg", { Size = UDim2.fromOffset(470, 30), Position = UDim2.fromOffset(80, 40), ScaleType = Enum.ScaleType.Stretch })
local bossDamage = img(bossBar, "bh_boss_lifebar_damage", { Size = UDim2.fromOffset(450, 20), Position = UDim2.fromOffset(90, 45), ZIndex = 2 })
local bossFill = img(bossBar, "bh_boss_lifebar_fill", { Size = UDim2.fromOffset(450, 20), Position = UDim2.fromOffset(90, 45), ZIndex = 3 })
img(bossBar, "bh_boss_frame", { Size = UDim2.fromOffset(96, 96), Position = UDim2.fromOffset(0, 0), ZIndex = 4 })
local bossName = text(bossBar, "", { Font = HEADING, TextSize = 26, Size = UDim2.fromOffset(400, 30), Position = UDim2.fromOffset(100, 8),
	TextXAlignment = Enum.TextXAlignment.Left, TextColor3 = Color3.fromRGB(255, 220, 110), ZIndex = 5 })
local bossShown = 1

-- screen-edge damage glow and the GO arrow between waves
local glows = {
	img(hud, "bh_damage_glow_top", { Size = UDim2.new(1, 0, 0, 90), ScaleType = Enum.ScaleType.Stretch, ImageTransparency = 1, ImageColor3 = Color3.fromRGB(255, 40, 40) }),
	img(hud, "bh_damage_glow_bottom", { Size = UDim2.new(1, 0, 0, 90), Position = UDim2.new(0, 0, 1, -90), ScaleType = Enum.ScaleType.Stretch, ImageTransparency = 1, ImageColor3 = Color3.fromRGB(255, 40, 40) }),
	img(hud, "bh_damage_glow_left", { Size = UDim2.new(0, 90, 1, 0), ScaleType = Enum.ScaleType.Stretch, ImageTransparency = 1, ImageColor3 = Color3.fromRGB(255, 40, 40) }),
	img(hud, "bh_damage_glow_right", { Size = UDim2.new(0, 90, 1, 0), Position = UDim2.new(1, -90, 0, 0), ScaleType = Enum.ScaleType.Stretch, ImageTransparency = 1, ImageColor3 = Color3.fromRGB(255, 40, 40) }),
}
local goArrow = img(hud, "bh_brawler_hud_indicator_go", { Size = UDim2.fromOffset(120, 120), AnchorPoint = Vector2.new(0.5, 0.5),
	Position = UDim2.fromScale(0.5, 0.62), ImageTransparency = 1, ZIndex = 6 })

local bannerBurst = img(hud, "popup_icon_burst", { Size = UDim2.fromOffset(420, 360), Position = UDim2.new(0.5, -210, 0.22, 0),
	ImageTransparency = 1, ZIndex = 4 })
local bannerLabel = text(hud, "", { Font = HEADING, TextSize = 96, Size = UDim2.fromOffset(900, 120), Position = UDim2.new(0.5, -450, 0.32, 0),
	TextColor3 = Color3.fromRGB(255, 236, 120), TextTransparency = 1, TextStrokeTransparency = 1, ZIndex = 5 })
local hint = text(hud, "WASD move • Space jump • Left click combo • Right click / 1-2-3 power attacks • F super • 4-7 emotes • 8-0 power emotes • H heroes",
	{ Size = UDim2.new(1, -32, 0, 20), Position = UDim2.new(0, 16, 1, -22), TextSize = 15, TextColor3 = Color3.fromRGB(210, 240, 245),
		TextXAlignment = Enum.TextXAlignment.Left })
hint.TextTransparency = 0.15

local portraitHero, portraitAnim
local function setPortrait(hero)
	if portraitHero == hero then return end
	portraitHero = hero
	for _, c in portraitVp:GetChildren() do
		if not c:IsA("UICorner") then c:Destroy() end
	end
	portraitAnim = nil
	local src = SPSO:FindFirstChild("Previews") and SPSO.Previews:FindFirstChild(hero)
	if not src then return end
	local world = Instance.new("WorldModel")
	world.Parent = portraitVp
	local rig = src:Clone()
	rig.Parent = world
	local ext = rig:GetExtentsSize()
	local cam = Instance.new("Camera")
	cam.FieldOfView = 24
	cam.CFrame = CFrame.lookAt(Vector3.new(0, ext.Y * 0.82, -ext.Y * 1.25), Vector3.new(0, ext.Y * 0.8, 0))
	cam.Parent = portraitVp
	portraitVp.CurrentCamera = cam
	local ok, anim = pcall(ExactAnimator.new, HeroPack.get(hero), rig, { wrapModes = Config.WrapModes, skin = false })
	if ok then
		anim:Play("movement_idle")
		portraitAnim = anim
	end
end

local lastBanner = SPSO:GetAttribute("BannerSeq")
local function showBanner(str)
	bannerLabel.Text = str
	bannerLabel.TextTransparency, bannerLabel.TextStrokeTransparency = 0, 0.2
	bannerBurst.ImageTransparency = 0.1
	bannerBurst.Rotation = -8
	bannerLabel.TextSize = 124
	TweenService:Create(bannerLabel, TweenInfo.new(0.35, Enum.EasingStyle.Back), { TextSize = 96 }):Play()
	TweenService:Create(bannerBurst, TweenInfo.new(1.6), { Rotation = 8 }):Play()
	Sound.ui("windowIn")
	task.delay(1.8, function()
		TweenService:Create(bannerLabel, TweenInfo.new(0.6), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
		TweenService:Create(bannerBurst, TweenInfo.new(0.6), { ImageTransparency = 1 }):Play()
	end)
end
SPSO:GetAttributeChangedSignal("BannerSeq"):Connect(function()
	if SPSO:GetAttribute("BannerSeq") ~= lastBanner then
		lastBanner = SPSO:GetAttribute("BannerSeq")
		showBanner(SPSO:GetAttribute("Banner") or "")
	end
end)

local superReady = false
local lastHealth, glowT, lastWaveLeft = nil, 0, nil
local MEDALS = { "bronze", "silver", "gold", "adamantium" }
local function updateHUD(dt)
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	hud.Enabled = char ~= nil and not selecting
	if not char then return end
	local hero = char:GetAttribute("SPSO_Hero") or Config.DefaultHero
	heroName.Text = string.upper((Config.Heroes[hero] or {}).displayName or hero)
	setPortrait(hero)
	if portraitAnim then portraitAnim:Step(dt) end
	if hum then
		local f = math.clamp(hum.Health / math.max(1, hum.MaxHealth), 0, 1)
		lifeFill.Size = UDim2.fromScale(f, 1)
		local cur = lifeDamage.Size.X.Scale
		lifeDamage.Size = UDim2.fromScale(cur > f and math.max(f, cur - dt * 0.35) or f, 1)
		hpText.Text = string.format("%d / %d", math.ceil(hum.Health), hum.MaxHealth)
		if lastHealth and hum.Health < lastHealth - 0.5 then glowT = 0.6 end
		lastHealth = hum.Health
	end
	glowT = math.max(0, glowT - dt)
	for _, g in glows do g.ImageTransparency = 1 - glowT end
	local power = player:GetAttribute("SPSO_Power") or 0
	pwFill.Size = UDim2.fromScale(math.clamp(power / Config.SuperCost, 0, 1), 1)
	for _, st in stars do
		local on = power + 1e-6 >= st.cost
		st.img.Image = on and (G.bh_star_active or "") or (G.bh_star_normal or "")
		st.img.Rotation = on and math.sin(os.clock() * 3) * 8 or 0
	end
	for _, pb in powerButtons do
		local ready = power + 1e-6 >= pb.cost
		pb.button.ImageTransparency = ready and 0 or 0.55
		pb.ring.ImageTransparency = ready and (0.25 + 0.25 * math.sin(os.clock() * 6)) or 1
	end
	if power >= Config.SuperCost and not superReady then Sound.ui("achievement") end
	superReady = power >= Config.SuperCost
	local heat = player:GetAttribute("SPSO_Combo") or 0
	local mult = math.floor(math.min(heat, GameData.Scoring.comboMax - 1)) + 1
	comboText.Text = string.format("COMBO x%d  •  SURVIVAL x%.2g", mult, SPSO:GetAttribute("SurvivalBonus") or 2)
	comboFill.Size = UDim2.new(0, 200 * math.clamp(heat / GameData.Scoring.comboMax, 0, 1), 0, 5)
	local score = SPSO:GetAttribute("TeamScore") or 0
	scoreText.Text = tostring(score)
	local medal = "bronze"
	for _, m in { "silver", "gold", "adamantium" } do
		local need = SPSO:GetAttribute("Medal" .. m:sub(1, 1):upper() .. m:sub(2))
		if need and score >= need then medal = m end
	end
	medalIcon.Image = G["bh_brawler_points_" .. medal] or ""
	local w = SPSO:GetAttribute("Wave")
	local left = SPSO:GetAttribute("EnemiesLeft") or 0
	waveLabel.Text = w and string.format("WAVE %d / %d  •  INVADERS LEFT %d", w, SPSO:GetAttribute("Waves") or 0, left) or ""
	if lastWaveLeft and lastWaveLeft > 0 and left == 0 and SPSO:GetAttribute("State") == "playing" then
		goArrow.ImageTransparency = 0
		goArrow.Size = UDim2.fromOffset(160, 160)
		TweenService:Create(goArrow, TweenInfo.new(0.4, Enum.EasingStyle.Back), { Size = UDim2.fromOffset(120, 120) }):Play()
		task.delay(2, function() TweenService:Create(goArrow, TweenInfo.new(0.4), { ImageTransparency = 1 }):Play() end)
		Sound.ui("HUD_Brawler_Char_Combo_Bonus")
	end
	lastWaveLeft = left
	-- enemies: original health bars, the boss on the big bar
	local boss
	for model, d in decor do
		local h = model:FindFirstChildOfClass("Humanoid")
		local hrp = model:FindFirstChild("HumanoidRootPart")
		if d.bar and h then
			local f = math.clamp(h.Health / math.max(1, h.MaxHealth), 0, 1)
			d.bar.fill.Size = UDim2.fromScale(f, 1)
			d.bar.shown = math.max(f, (d.bar.shown or 1) - dt * 0.5)
			d.bar.damage.Size = UDim2.fromScale(d.bar.shown, 1)
			d.bar.gui.Enabled = h.Health > 0 and not model:GetAttribute("SPSO_Boss")
			if model:GetAttribute("SPSO_Boss") and h.Health > 0 then boss = model end
		end
		if d.shadow and hrp then
			local ray = workspace:Raycast(hrp.Position, Vector3.new(0, -14, 0), RaycastParams.new())
			local y = ray and ray.Position.Y or (hrp.Position.Y - 3.3)
			d.shadow.CFrame = CFrame.new(hrp.Position.X, y + 0.06, hrp.Position.Z)
		end
	end
	bossBar.Visible = boss ~= nil
	if boss then
		local h = boss:FindFirstChildOfClass("Humanoid")
		local f = math.clamp(h.Health / math.max(1, h.MaxHealth), 0, 1)
		bossName.Text = string.upper(boss.Name)
		bossFill.Size = UDim2.fromOffset(450 * f, 20)
		bossShown = math.max(f, bossShown - dt * 0.3)
		bossDamage.Size = UDim2.fromOffset(450 * bossShown, 20)
	else
		bossShown = 1
	end
	-- target ring and own ring
	targetModel = nearestEnemy(22)
	local tr = targetModel and targetModel.PrimaryPart
	if tr then
		local y = tr.Position.Y - 3.25
		ringPart.CFrame = CFrame.new(tr.Position.X, y, tr.Position.Z) * CFrame.Angles(0, os.clock() * 1.5, 0)
		arrowPart.CFrame = CFrame.new(tr.Position.X, y + 0.02, tr.Position.Z) * CFrame.Angles(0, -os.clock() * 2, 0)
		arrowPart.Size = Vector3.new(9 + math.sin(os.clock() * 5) * 0.6, 0.05, 9 + math.sin(os.clock() * 5) * 0.6)
	else
		ringPart.CFrame = CFrame.new(0, -500, 0)
		arrowPart.CFrame = CFrame.new(0, -500, 0)
	end
	local hrp = char:FindFirstChild("HumanoidRootPart")
	if hrp then selfRing.CFrame = CFrame.new(hrp.Position.X, hrp.Position.Y - 3.27, hrp.Position.Z) end
end

-- music: the stage tracks the server names, menu music on the select screen
SPSO:GetAttributeChangedSignal("Music"):Connect(function()
	if not selecting and SPSO:GetAttribute("State") ~= "results" then Sound.music(SPSO:GetAttribute("Music")) end
end)

-- effects from the server ---------------------------------------------------------------------------------------------------
local fxGui = screen("SPSO_FxText", 2)
local function popText(pos: Vector3, str: string, color: Color3, size: number)
	local holder = Instance.new("Attachment")
	holder.WorldPosition = pos
	holder.Parent = workspace.Terrain
	local bb = Instance.new("BillboardGui")
	bb.Size = UDim2.fromOffset(200, 60)
	bb.StudsOffsetWorldSpace = Vector3.new(math.random() * 2 - 1, 1, 0)
	bb.AlwaysOnTop = true
	bb.Adornee = holder
	local t = text(bb, str, { Size = UDim2.fromScale(1, 1), Font = HEADING, TextSize = size, TextColor3 = color, TextStrokeTransparency = 0 })
	bb.Parent = fxGui
	TweenService:Create(bb, TweenInfo.new(0.9), { StudsOffsetWorldSpace = bb.StudsOffsetWorldSpace + Vector3.new(0, 4, 0) }):Play()
	TweenService:Create(t, TweenInfo.new(0.9), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
	Debris:AddItem(holder, 1)
	Debris:AddItem(bb, 1)
end

local function spark(pos: Vector3, color: Color3, size: number)
	local p = Instance.new("Part")
	p.Shape = Enum.PartType.Ball
	p.Material = Enum.Material.Neon
	p.Color = color
	p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch, p.CastShadow = true, false, false, false, false
	p.Size = Vector3.one * 1.2
	p.Position = pos
	p.Parent = workspace
	TweenService:Create(p, TweenInfo.new(0.22), { Size = Vector3.one * size, Transparency = 1 }):Play()
	Debris:AddItem(p, 0.25)
end

local projVisuals = {}
local PROJ = {
	bolt = { size = 0.7, color = Color3.fromRGB(120, 255, 140) }, web = { size = 1.1, color = Color3.fromRGB(240, 240, 255) },
	shard = { size = 0.6, color = Color3.fromRGB(255, 200, 120) }, orb = { size = 1.4, color = Color3.fromRGB(255, 220, 110) },
}

FxRemote.OnClientEvent:Connect(function(kind, data)
	if kind == "hit" then
		local played = data.effect and FxPlayer.play(data.hero, data.effect, nil, { at = data.pos })
		if not played then spark(data.pos, data.team == "Hero" and Color3.fromRGB(255, 90, 90) or Color3.fromRGB(255, 230, 120), data.heavy and 6 or 4) end
		popText(data.pos, tostring(data.amount), data.team == "Hero" and Color3.fromRGB(255, 110, 110) or Color3.fromRGB(255, 240, 150),
			data.heavy and 40 or 30)
		local char = player.Character
		if data.heavy and char and char.PrimaryPart and (char.PrimaryPart.Position - data.pos).Magnitude < 40 then
			shake = math.max(shake, 0.7)
		end
	elseif kind == "beam" then
		FxPlayer.beam(data.hero, data.from, data.to, 0.2)
	elseif kind == "proj" then
		local spec = PROJ[data.kind] or PROJ.orb
		local p = Instance.new("Part")
		p.Shape = Enum.PartType.Ball
		p.Material = Enum.Material.Neon
		p.Color = spec.color
		p.Size = Vector3.one * spec.size
		p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch, p.CastShadow = true, false, false, false, false
		p.Position = data.from
		local a0, a1 = Instance.new("Attachment"), Instance.new("Attachment")
		a0.Position, a1.Position = Vector3.new(0, spec.size / 2, 0), Vector3.new(0, -spec.size / 2, 0)
		a0.Parent, a1.Parent = p, p
		local tr = Instance.new("Trail")
		tr.Attachment0, tr.Attachment1 = a0, a1
		tr.Lifetime = 0.25
		tr.Color = ColorSequence.new(spec.color)
		tr.Transparency = NumberSequence.new(0.2, 1)
		tr.LightEmission = 1
		tr.Texture = Assets.Fx.trail_additive_tex_7656 or ""
		tr.FaceCamera = true
		tr.Parent = p
		p.Parent = workspace
		projVisuals[data.id] = { part = p, vel = data.vel, g = data.g or 0, expires = os.clock() + data.life }
	elseif kind == "projEnd" then
		local v = projVisuals[data.id]
		if v then
			v.part:Destroy()
			projVisuals[data.id] = nil
		end
		if data.hit == false then spark(data.pos, Color3.fromRGB(255, 255, 255), 2.5) end
	elseif kind == "score" then
		popText(data.pos, "+" .. data.points .. (data.mult > 1 and (" x" .. data.mult) or ""), Color3.fromRGB(120, 255, 160), 34)
		Sound.ui("coins")
	elseif kind == "pickup" then
		Sound.ui(data.kind == "star" and "star" or "xp")
		popText(data.pos, data.kind == "star" and "+" .. GameData.Scoring.pickupBonus or "+HEALTH", Color3.fromRGB(255, 230, 90), 28)
	elseif kind == "denied" then
		Sound.ui("alert")
		pwFill.BackgroundColor3 = Color3.fromRGB(255, 60, 60)
		task.delay(0.25, function() pwFill.BackgroundColor3 = Color3.fromRGB(255, 200, 60) end)
	elseif kind == "bossKO" then
		Sound.play("FX_Brawler_Boss_Knockout", { channel = "ui" })
		shake = math.max(shake, 1.2)
	elseif kind == "push" then
		pushVel, pushUntil = data.vel, os.clock() + math.max(0.1, data.time or 0.25)
	elseif kind == "spawn" then
		local m = data.model
		local pos = m and m.PrimaryPart and m.PrimaryPart.Position
		if pos then
			Sound.play("Fx_Spawn_Char_SpawnIn_1", { at = pos, volume = 0.8 })
			local ring = groundDecal("ring_sharp_additive_tex", 2, Color3.fromRGB(150, 230, 255), 0)
			ring.CFrame = CFrame.new(pos - Vector3.new(0, 3.2, 0))
			TweenService:Create(ring, TweenInfo.new(0.6), { Size = Vector3.new(14, 0.05, 14) }):Play()
			TweenService:Create(ring:FindFirstChildOfClass("Decal"), TweenInfo.new(0.6), { Transparency = 1 }):Play()
			Debris:AddItem(ring, 0.65)
		end
	end
end)

-- pickups: spin and glow
local function decoratePickup(p: Instance)
	if not p:IsA("BasePart") then return end
	local bb = Instance.new("BillboardGui")
	bb.Size = UDim2.fromOffset(46, 46)
	bb.AlwaysOnTop = false
	bb.Adornee = p
	img(bb, p:GetAttribute("Kind") == "star" and "loading_star" or "popup_icon_burst", { Size = UDim2.fromScale(1, 1),
		ImageColor3 = p:GetAttribute("Kind") == "star" and Color3.new(1, 1, 1) or Color3.fromRGB(255, 110, 140) })
	bb.Parent = p
	p.Transparency = 0.6
end
local pickupFolder = workspace:WaitForChild("SPSO_Pickups", 30)
if pickupFolder then
	pickupFolder.ChildAdded:Connect(decoratePickup)
	for _, p in pickupFolder:GetChildren() do decoratePickup(p) end
end

-- loading screen -------------------------------------------------------------------------------------------------------------
local loading = screen("SPSO_Loading", 20)
local bgKeys = { "loading_background_0", "loading_background_1", "loading_background_2", "loading_background_4",
	"loading_background_5", "loading_background_6" }
img(loading, bgKeys[math.random(#bgKeys)], { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Crop })
local rays = img(loading, "light_rays_top_layer", { Size = UDim2.fromOffset(1400, 1400), AnchorPoint = Vector2.new(0.5, 0.5),
	Position = UDim2.fromScale(0.5, 0.45), ImageTransparency = 0.55 })
text(loading, "SUPER SQUAD BRAWL", { Font = HEADING, TextSize = 84, Size = UDim2.new(1, 0, 0, 90), Position = UDim2.fromScale(0, 0.18),
	TextColor3 = Color3.fromRGB(255, 236, 120), TextStrokeTransparency = 0 })
local tipBox = img(loading, "loading_tipbox_leftside", { Size = UDim2.fromOffset(560, 150), AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.fromScale(0.5, 0.56), ScaleType = Enum.ScaleType.Slice, SliceCenter = Rect.new(80, 40, 120, 110) })
local tipText = text(tipBox, Config.Tips[math.random(#Config.Tips)], { Size = UDim2.new(1, -170, 1, -30), Position = UDim2.fromOffset(150, 15),
	TextWrapped = true, TextSize = 22, TextColor3 = Color3.fromRGB(40, 60, 20), TextStrokeTransparency = 1 })
local barFrame = img(loading, "loading_bar_frame", { Size = UDim2.fromOffset(640, 80), AnchorPoint = Vector2.new(0.5, 0),
	Position = UDim2.fromScale(0.5, 0.8) })
local barFill = img(barFrame, "loading_bar_fill", { Size = UDim2.new(0, 0, 0.38, 0), Position = UDim2.fromScale(0.08, 0.31), ScaleType = Enum.ScaleType.Stretch })
local star = img(loading, "loading_star", { Size = UDim2.fromOffset(42, 42), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.79) })
local loadText = text(loading, "LOADING...", { Font = HEADING, TextSize = 30, Size = UDim2.new(1, 0, 0, 32), Position = UDim2.fromScale(0, 0.89) })

Sound.music(Config.Music.menu)
local loadProgress = 0
task.spawn(function()
	local sprite = Instance.new("Sound")
	sprite.SoundId = Assets.SoundSprite
	local list = { sprite }
	for _, id in G do table.insert(list, id) end
	for _, id in Assets.Fx do table.insert(list, id) end
	local done = 0
	pcall(function()
		ContentProvider:PreloadAsync(list, function()
			done += 1
			loadProgress = math.max(loadProgress, 0.7 * done / #list)
		end)
	end)
	for i, hero in Config.HeroOrder do
		pcall(HeroPack.get, hero)
		loadProgress = math.max(loadProgress, 0.7 + 0.3 * i / #Config.HeroOrder)
		task.wait()
	end
	loadProgress = 1
end)

-- hero select ----------------------------------------------------------------------------------------------------------------
local selectGui = screen("SPSO_Select", 10)
selectGui.Enabled = false
img(selectGui, "preloading_blue_backdrop", { Size = UDim2.fromScale(1, 1), ScaleType = Enum.ScaleType.Crop })
local selRays = img(selectGui, "light_rays_top_layer", { Size = UDim2.fromOffset(1500, 1500), AnchorPoint = Vector2.new(0.5, 0.5),
	Position = UDim2.fromScale(0.5, 0.5), ImageTransparency = 0.7 })
text(selectGui, "CHOOSE YOUR HERO", { Font = HEADING, TextSize = 64, Size = UDim2.new(1, 0, 0, 70), Position = UDim2.fromScale(0, 0.04),
	TextColor3 = Color3.fromRGB(255, 236, 120), TextStrokeTransparency = 0 })
local cards = Instance.new("Frame")
cards.BackgroundTransparency = 1
cards.Size, cards.Position = UDim2.new(1, -40, 0.72, 0), UDim2.fromScale(0, 0.16) + UDim2.fromOffset(20, 0)
cards.Parent = selectGui
local cl = Instance.new("UIListLayout", cards)
cl.FillDirection = Enum.FillDirection.Horizontal
cl.HorizontalAlignment = Enum.HorizontalAlignment.Center
cl.VerticalAlignment = Enum.VerticalAlignment.Center
cl.Padding = UDim.new(0, 14)

local previews = {}
local function makeCard(hero: string)
	local cfg, info, d = Config.Heroes[hero], Config.HeroInfo[hero] or {}, GameData.Heroes[hero]
	local card = Instance.new("ImageButton")
	card.Size = UDim2.new(0.18, 0, 1, 0)
	card.BackgroundTransparency = 1
	card.Image = G.mcentral_content_panel_bg or ""
	card.ScaleType = Enum.ScaleType.Stretch
	card.Parent = cards
	local aspect = Instance.new("UIAspectRatioConstraint", card)
	aspect.AspectRatio = 0.62
	local scale = Instance.new("UIScale", card)
	local vp = Instance.new("ViewportFrame")
	vp.Size, vp.Position = UDim2.fromScale(0.84, 0.58), UDim2.fromScale(0.08, 0.06)
	vp.BackgroundColor3 = info.color or Color3.fromRGB(40, 60, 90)
	vp.BackgroundTransparency = 0.25
	vp.Ambient, vp.LightColor, vp.LightDirection = Color3.fromRGB(170, 170, 180), Color3.new(1, 1, 1), Vector3.new(-0.4, -1, -0.6)
	vp.Parent = card
	Instance.new("UICorner", vp).CornerRadius = UDim.new(0, 14)
	img(card, (info.class or "strength") .. "_icon", { Size = UDim2.fromScale(0.16, 0.1), Position = UDim2.fromScale(0.1, 0.08), ZIndex = 3,
		ScaleType = Enum.ScaleType.Fit })
	text(card, string.upper(cfg.displayName), { Font = HEADING, TextSize = 30, Size = UDim2.fromScale(1, 0.09), Position = UDim2.fromScale(0, 0.65),
		TextColor3 = Color3.fromRGB(255, 250, 230), TextStrokeTransparency = 0 })
	text(card, info.tagline or "", { TextSize = 13, TextWrapped = true, Size = UDim2.fromScale(0.68, 0.12), Position = UDim2.fromScale(0.16, 0.73),
		TextColor3 = Color3.fromRGB(70, 50, 10), TextStrokeTransparency = 1 })
	text(card, string.format("HEALTH %d   •   SPEED %d", d.health, math.floor(d.speed / Config.StudsPerUnit + 0.5)),
		{ TextSize = 13, Size = UDim2.fromScale(1, 0.06), Position = UDim2.fromScale(0, 0.87), TextColor3 = Color3.fromRGB(110, 70, 10),
			TextStrokeTransparency = 1 })
	card.MouseEnter:Connect(function()
		Sound.ui("hover")
		TweenService:Create(scale, TweenInfo.new(0.12), { Scale = 1.06 }):Play()
		local p = previews[hero]
		if p then p.anim:CrossFade(p.anim:HasClip("emote_cheer") and "emote_cheer" or "movement_idle", 0.2) end
	end)
	card.MouseLeave:Connect(function()
		TweenService:Create(scale, TweenInfo.new(0.12), { Scale = 1 }):Play()
		local p = previews[hero]
		if p then p.anim:CrossFade("movement_idle", 0.3) end
	end)
	card.Activated:Connect(function()
		Sound.ui("clickBig")
		SelectRemote:FireServer(hero)
		selectGui.Enabled = false
		selecting = false
		Sound.music(SPSO:GetAttribute("Music") or Config.Music.loading)
	end)
	-- live preview: the hero's rig posed by its own exact animator
	task.spawn(function()
		local src = SPSO:WaitForChild("Previews", 30) and SPSO.Previews:WaitForChild(hero, 30)
		if not src then return end
		local world = Instance.new("WorldModel")
		world.Parent = vp
		local rig = src:Clone()
		rig.Parent = world
		local ext = rig:GetExtentsSize()
		local cam = Instance.new("Camera")
		cam.FieldOfView = 30
		local h = math.max(4, ext.Y)
		cam.CFrame = CFrame.lookAt(Vector3.new(0, h * 0.55, -h * 2.3), Vector3.new(0, h * 0.48, 0))
		cam.Parent = vp
		vp.CurrentCamera = cam
		local ok, anim = pcall(ExactAnimator.new, HeroPack.get(hero), rig, { wrapModes = Config.WrapModes, skin = false,
			faceTextures = nil, headPart = cfg.headPart })
		if ok then
			local st = anim:GetState("movement_idle")
			st.wrapMode = 2
			anim:Play("movement_idle")
			previews[hero] = { anim = anim, rig = rig }
		end
	end)
end
for _, hero in Config.HeroOrder do makeCard(hero) end
text(selectGui, "Click a hero to jump in  •  press H in game to switch", { TextSize = 20, Size = UDim2.new(1, 0, 0, 26), Position = UDim2.fromScale(0, 0.92) })

showSelect = function()
	selecting = true
	selectGui.Enabled = true
	hud.Enabled = false
	Sound.ui("windowIn")
	Sound.music(Config.Music.select)
end

-- results: the original mission complete screen ----------------------------------------------------------------------
local results = screen("SPSO_Results", 15)
results.Enabled = false
local dim = Instance.new("Frame")
dim.Size, dim.BackgroundColor3, dim.BackgroundTransparency = UDim2.fromScale(1, 1), Color3.new(0, 0, 0), 0.45
dim.Parent = results
local rays1 = img(results, "bh_mc_rays2", { Size = UDim2.fromOffset(900, 900), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.42), ImageTransparency = 0.2 })
local rays2 = img(results, "bh_stagecomplete_rays", { Size = UDim2.fromOffset(700, 700), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.42), ImageTransparency = 0.15 })
img(results, "bh_backstar", { Size = UDim2.fromOffset(330, 330), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.4) })
local sparkles = img(results, "bh_mc_sparkles", { Size = UDim2.fromOffset(360, 360), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.4) })
local bigMedal = img(results, "bh_brawler_points_gold", { Size = UDim2.fromOffset(190, 190), AnchorPoint = Vector2.new(0.5, 0.5), Position = UDim2.fromScale(0.5, 0.4) })
text(results, "MISSION COMPLETE!", { Font = HEADING, TextSize = 72, Size = UDim2.new(1, 0, 0, 80), Position = UDim2.fromScale(0, 0.08),
	TextColor3 = Color3.fromRGB(255, 220, 80), TextStrokeTransparency = 0 })
local medalText = text(results, "", { Font = HEADING, TextSize = 44, Size = UDim2.new(1, 0, 0, 50), Position = UDim2.fromScale(0, 0.58) })
local resPanel = img(results, "bh_background", { Size = UDim2.fromOffset(520, 170), AnchorPoint = Vector2.new(0.5, 0), Position = UDim2.fromScale(0.5, 0.66) })
local resText = text(resPanel, "", { TextSize = 22, Size = UDim2.new(0.86, 0, 0.8, 0), Position = UDim2.fromScale(0.07, 0.1),
	TextWrapped = true, TextColor3 = Color3.fromRGB(40, 60, 10), TextStrokeTransparency = 1 })
local MEDAL_COLORS = { Bronze = Color3.fromRGB(205, 127, 50), Silver = Color3.fromRGB(200, 210, 220), Gold = Color3.fromRGB(255, 205, 40),
	Adamantium = Color3.fromRGB(120, 230, 255) }
SPSO:GetAttributeChangedSignal("State"):Connect(function()
	local s = SPSO:GetAttribute("State")
	if s == "results" then
		local medal = SPSO:GetAttribute("Medal") or "Bronze"
		medalText.Text = string.upper(medal) .. " MEDAL"
		medalText.TextColor3 = MEDAL_COLORS[medal] or Color3.new(1, 1, 1)
		bigMedal.Image = G["bh_brawler_points_" .. string.lower(medal)] or ""
		resText.Text = string.format("Team score %d\nKnockouts %d  •  Time %d:%02d\nSilver %d  •  Gold %d  •  Adamantium %d",
			SPSO:GetAttribute("TeamScore") or 0, SPSO:GetAttribute("KOs") or 0, (SPSO:GetAttribute("RunTime") or 0) // 60,
			(SPSO:GetAttribute("RunTime") or 0) % 60, SPSO:GetAttribute("MedalSilver") or 0, SPSO:GetAttribute("MedalGold") or 0,
			SPSO:GetAttribute("MedalAdamantium") or 0)
		results.Enabled = true
		bigMedal.Size = UDim2.fromOffset(40, 40)
		TweenService:Create(bigMedal, TweenInfo.new(0.6, Enum.EasingStyle.Back), { Size = UDim2.fromOffset(190, 190) }):Play()
		Sound.music(Config.Music.complete)
		Sound.play("FX_Brawler_game_Mission_Complete_Fireworks", { channel = "ui" })
		Sound.play("FX_Brawler_Cheer", { channel = "ui" })
		task.delay(5.5, function() if results.Enabled then Sound.music(Config.Music.completeLoop) end end)
		task.delay(Config.ResultsTime - 1, function() results.Enabled = false end)
	elseif s == "playing" then
		results.Enabled = false
	end
end)
RunService.RenderStepped:Connect(function(dt)
	if results.Enabled then
		rays1.Rotation += dt * 8
		rays2.Rotation -= dt * 12
		sparkles.Rotation += dt * 20
	end
end)

-- frame loop -----------------------------------------------------------------------------------------------------------------------
local loadingDone = false
RunService.PreRender:Connect(function(dt)
	if not loadingDone then
		rays.Rotation += dt * 6
		star.Rotation += dt * 180
		barFill.Size = UDim2.new(0.84 * loadProgress, 0, 0.38, 0)
		loadText.Text = string.format("LOADING... %d%%", math.floor(loadProgress * 100))
		if loadProgress >= 1 then
			loadingDone = true
			TweenService:Create(tipText, TweenInfo.new(0.3), { TextTransparency = 1 }):Play()
			task.delay(0.3, function()
				loading.Enabled = false
				if not player.Character then showSelect() end
			end)
		end
	end
	if selecting then
		selRays.Rotation += dt * 4
		for _, p in previews do p.anim:Step(dt) end
	end
	for model, ca in animators do
		if type(ca) == "table" then
			if not model.Parent then
				detach(model)
			else
				local ok, err = pcall(ca.Update, ca, dt)
				if not ok then
					warn("[SPSO] " .. tostring(err))
					detach(model)
				end
			end
		end
	end
	FxPlayer.update(dt)
	for id, v in projVisuals do
		if os.clock() > v.expires or not v.part.Parent then
			v.part:Destroy()
			projVisuals[id] = nil
		else
			v.vel += Vector3.new(0, -v.g * dt, 0)
			v.part.Position += v.vel * dt
		end
	end
	updateLocal()
	updateCamera(dt)
	updateHUD(dt)
end)

player.CharacterAdded:Connect(function()
	selecting = false
	selectGui.Enabled = false
	if loadingDone then Sound.music(SPSO:GetAttribute("Music") or Config.Music.loading) end
end)
