-- SPSO brawler client: animates every fighter with the exact animation runtime, the original
-- brawler-style fixed camera, input (attacks, super, emotes), HUD, hit effects, enemy costume recolors.
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local UserInputService = game:GetService("UserInputService")
local ContextActionService = game:GetService("ContextActionService")
local CollectionService = game:GetService("CollectionService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local AssetService = game:GetService("AssetService")
local TweenService = game:GetService("TweenService")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local Net = require(Game:WaitForChild("Net"))
local CharacterAnimator = require(Game:WaitForChild("CharacterAnimator"))

local player = Players.LocalPlayer
local AttackRemote, EmoteRemote, FxRemote = Net.event("Attack"), Net.event("Emote"), Net.event("Fx")
local heroCfg = Config.Heroes[Config.PlayerHero]

-- enemy costume recolors (EditableImage hue shift of the crimson costume; skin, mane, tape untouched) --
local recolored = {}
local function hsv2rgb(h, s, v)
	local i = math.floor(h * 6) % 6
	local f = h * 6 - math.floor(h * 6)
	local p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
	if i == 0 then return v, t, p elseif i == 1 then return q, v, p elseif i == 2 then return p, v, t
	elseif i == 3 then return p, q, v elseif i == 4 then return t, p, v end
	return v, p, q
end

local function recolor(content: Content, key: string, variant)
	if recolored[key] ~= nil then
		while recolored[key] == "busy" do task.wait() end
		return recolored[key]
	end
	recolored[key] = "busy"
	local ok, ei = pcall(AssetService.CreateEditableImageAsync, AssetService, content)
	if not ok then
		warn("[SPSO] recolor unavailable: " .. tostring(ei))
		recolored[key] = false
		return false
	end
	local size = ei.Size
	local buf = ei:ReadPixelsBuffer(Vector2.zero, size)
	local n = size.X * size.Y
	for i = 0, n - 1 do
		local o = i * 4
		local r, g, b = buffer.readu8(buf, o) / 255, buffer.readu8(buf, o + 1) / 255, buffer.readu8(buf, o + 2) / 255
		local mx, mn = math.max(r, g, b), math.min(r, g, b)
		local d = mx - mn
		if mx > 0.06 and d > 0.42 * mx then
			local h
			if mx == r then h = ((g - b) / d) % 6 elseif mx == g then h = (b - r) / d + 2 else h = (r - g) / d + 4 end
			h /= 6
			local s = d / mx
			local nr, ng, nb
			if h > 0.93 or h < 0.025 then
				nr, ng, nb = hsv2rgb(variant.hue, math.clamp(s * variant.sat, 0, 1), math.clamp(mx * variant.val, 0, 1))
			elseif variant.gold == "silver" and h > 0.09 and h < 0.17 and s > 0.45 then
				nr, ng, nb = hsv2rgb(0.58, s * 0.12, math.clamp(mx * 1.05, 0, 1))
			end
			if nr then
				buffer.writeu8(buf, o, math.floor(nr * 255 + 0.5))
				buffer.writeu8(buf, o + 1, math.floor(ng * 255 + 0.5))
				buffer.writeu8(buf, o + 2, math.floor(nb * 255 + 0.5))
			end
		end
		if i % 131072 == 0 then task.wait() end
	end
	ei:WritePixelsBuffer(Vector2.zero, size, buf)
	local c = Content.fromObject(ei)
	recolored[key] = c
	return c
end

local function applyVariant(ca, model: Model, variantName: string)
	local variant
	for _, v in Config.Variants do
		if v.name == variantName then variant = v end
	end
	if not variant then return end
	for _, partName in { ca.cfg.bodyPart, ca.cfg.headPart } do
		local part = model:FindFirstChild(partName, true)
		if part and part:IsA("MeshPart") then
			local c = recolor(part.TextureContent, partName .. "/" .. variant.name, variant)
			if c and model.Parent then ca.anim:SetPartTexture(partName, c) end
		end
	end
end

-- animators for every fighter ----------------------------------------------------------------------------
local animators = {}
local healthBars = {}

local function makeHealthBar(model: Model)
	local hrp = model:FindFirstChild("HumanoidRootPart")
	if not hrp then return end
	local bb = Instance.new("BillboardGui")
	bb.Name = "SPSO_Health"
	bb.Size = UDim2.fromOffset(90, 10)
	bb.StudsOffset = Vector3.new(0, 5.6, 0)
	bb.AlwaysOnTop = true
	bb.Adornee = hrp
	local bg = Instance.new("Frame")
	bg.Size = UDim2.fromScale(1, 1)
	bg.BackgroundColor3 = Color3.fromRGB(25, 20, 30)
	bg.BorderSizePixel = 0
	bg.Parent = bb
	Instance.new("UICorner", bg).CornerRadius = UDim.new(0, 4)
	local fill = Instance.new("Frame")
	fill.Size = UDim2.fromScale(1, 1)
	fill.BackgroundColor3 = Color3.fromRGB(235, 70, 70)
	fill.BorderSizePixel = 0
	fill.Parent = bg
	Instance.new("UICorner", fill).CornerRadius = UDim.new(0, 4)
	bb.Parent = player:WaitForChild("PlayerGui")
	healthBars[model] = { gui = bb, fill = fill }
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
		while #root:GetDescendants() < 39 and os.clock() - t0 < 10 do task.wait() end
		local isLocal = model == player.Character
		local variant = model:GetAttribute("SPSO_Variant")
		local enemy = model:GetAttribute("SPSO_Team") == "Enemy"
		local ok, ca = pcall(CharacterAnimator.new, model, {
			isLocal = isLocal, skin = true, prebuildSkin = isLocal,
			faces = not (variant and variant ~= ""), lodDistance = isLocal and 300 or 80,
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
		if enemy then makeHealthBar(model) end
		if variant and variant ~= "" then task.spawn(applyVariant, ca, model, variant) end
	end)
end

local function detach(model: Instance)
	local ca = animators[model]
	if type(ca) == "table" then ca:Destroy() end
	animators[model] = nil
	local hb = healthBars[model]
	if hb then hb.gui:Destroy() end
	healthBars[model] = nil
end

CollectionService:GetInstanceAddedSignal("SPSO_Fighter"):Connect(attach)
CollectionService:GetInstanceRemovedSignal("SPSO_Fighter"):Connect(detach)
for _, m in CollectionService:GetTagged("SPSO_Fighter") do attach(m) end

-- camera ----------------------------------------------------------------------------------------------------
local camera = workspace.CurrentCamera
local zoom, camFocus, shake = 1, nil, 0
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
	camFocus = camFocus and camFocus:Lerp(focus, 1 - math.exp(-7 * dt)) or focus
	local jitter = Vector3.zero
	if shake > 0 then
		shake = math.max(0, shake - dt * 2.5)
		jitter = Vector3.new(math.random() - 0.5, math.random() - 0.5, 0) * shake
	end
	camera.FieldOfView = Config.Camera.fov
	camera.CFrame = CFrame.lookAt(camFocus + Config.Camera.offset * zoom + jitter, camFocus + jitter * 0.5)
end

-- movement lock during actions, emote cancel by moving ------------------------------------------------------
local function updateLocal()
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	if not hum then return end
	local locked = char:GetAttribute("SPSO_Lock") == true or char:GetAttribute("SPSO_Dead") == true
	hum.WalkSpeed = locked and 0 or heroCfg.walkSpeed
	hum.UseJumpPower = true
	hum.JumpPower = locked and 0 or heroCfg.jumpPower
	hum.AutoRotate = not locked
	local ca = animators[char]
	if type(ca) == "table" and ca:Current() and string.sub(ca:Current(), 1, 6) == "emote_" and hum.MoveDirection.Magnitude > 0.1 then
		EmoteRemote:FireServer(0)
	end
end

-- input ----------------------------------------------------------------------------------------------------
local function faceNearestEnemy()
	local char = player.Character
	local hrp = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp or char:GetAttribute("SPSO_Lock") then return end
	local best, bd = nil, 16
	for m in animators do
		if m:GetAttribute("SPSO_Team") == "Enemy" and not m:GetAttribute("SPSO_Dead") and m.PrimaryPart then
			local d = (m.PrimaryPart.Position - hrp.Position).Magnitude
			if d < bd then best, bd = m.PrimaryPart, d end
		end
	end
	if best then
		local dir = (best.Position - hrp.Position) * Vector3.new(1, 0, 1)
		if dir.Magnitude > 0.1 then hrp.CFrame = CFrame.lookAt(hrp.Position, hrp.Position + dir) end
	end
end

local function bind(name: string, kind: string, ...)
	ContextActionService:BindAction(name, function(_, state)
		if state == Enum.UserInputState.Begin then
			faceNearestEnemy()
			AttackRemote:FireServer(kind)
		end
		return Enum.ContextActionResult.Sink
	end, true, ...)
	ContextActionService:SetTitle(name, kind == "Super" and "SUPER" or kind)
end
bind("SPSO_L", "L", Enum.UserInputType.MouseButton1, Enum.KeyCode.ButtonX)
bind("SPSO_R", "R", Enum.UserInputType.MouseButton2, Enum.KeyCode.ButtonY)
bind("SPSO_Super", "Super", Enum.KeyCode.F, Enum.KeyCode.ButtonB)
UserInputService.InputBegan:Connect(function(input, gp)
	if gp then return end
	local keys = { Enum.KeyCode.One, Enum.KeyCode.Two, Enum.KeyCode.Three, Enum.KeyCode.Four }
	local i = table.find(keys, input.KeyCode)
	if i then EmoteRemote:FireServer(i) end
end)

-- HUD ------------------------------------------------------------------------------------------------------------
local gui = Instance.new("ScreenGui")
gui.Name = "SPSO_HUD"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = true
gui.Parent = player:WaitForChild("PlayerGui")

local function label(parent, text, size, pos, ts, color)
	local l = Instance.new("TextLabel")
	l.BackgroundTransparency = 1
	l.Size, l.Position = size, pos
	l.Font = Enum.Font.FredokaOne
	l.Text, l.TextSize = text, ts
	l.TextColor3 = color or Color3.new(1, 1, 1)
	l.TextStrokeTransparency = 0.4
	l.Parent = parent
	return l
end

local function bar(parent, y, color)
	local bg = Instance.new("Frame")
	bg.Size, bg.Position = UDim2.new(1, -24, 0, 16), UDim2.fromOffset(12, y)
	bg.BackgroundColor3 = Color3.fromRGB(20, 24, 40)
	bg.BorderSizePixel = 0
	bg.Parent = parent
	Instance.new("UICorner", bg).CornerRadius = UDim.new(0, 6)
	local fill = Instance.new("Frame")
	fill.Size = UDim2.fromScale(1, 1)
	fill.BackgroundColor3 = color
	fill.BorderSizePixel = 0
	fill.Parent = bg
	Instance.new("UICorner", fill).CornerRadius = UDim.new(0, 6)
	return fill
end

local panel = Instance.new("Frame")
panel.Size, panel.Position = UDim2.fromOffset(300, 104), UDim2.fromOffset(16, 16)
panel.BackgroundColor3 = Color3.fromRGB(14, 40, 62)
panel.BackgroundTransparency = 0.2
panel.Parent = gui
Instance.new("UICorner", panel).CornerRadius = UDim.new(0, 12)
local stroke = Instance.new("UIStroke", panel)
stroke.Color, stroke.Thickness = Color3.fromRGB(120, 220, 235), 2
local nameLabel = label(panel, string.upper(heroCfg.displayName), UDim2.new(1, -24, 0, 28), UDim2.fromOffset(12, 6), 24)
nameLabel.TextXAlignment = Enum.TextXAlignment.Left
local hpFill = bar(panel, 40, Color3.fromRGB(235, 70, 70))
local pwFill = bar(panel, 64, Color3.fromRGB(255, 200, 60))
local pwLabel = label(panel, "", UDim2.new(1, -24, 0, 16), UDim2.fromOffset(12, 83), 14, Color3.fromRGB(255, 225, 140))
pwLabel.TextXAlignment = Enum.TextXAlignment.Left

local waveLabel = label(gui, "", UDim2.fromOffset(400, 34), UDim2.new(0.5, -200, 0, 18), 28)
local bannerLabel = label(gui, "", UDim2.fromOffset(900, 120), UDim2.new(0.5, -450, 0.32, 0), 96, Color3.fromRGB(255, 230, 120))
bannerLabel.TextTransparency, bannerLabel.TextStrokeTransparency = 1, 1
local hint = label(gui, "WASD move  •  Space jump  •  Left click combo  •  Right click heavy  •  F super  •  1-4 emotes",
	UDim2.new(1, -32, 0, 22), UDim2.new(0, 16, 1, -34), 18, Color3.fromRGB(210, 240, 245))
hint.TextXAlignment = Enum.TextXAlignment.Left

local lastBanner = SPSO:GetAttribute("BannerSeq")
local function showBanner()
	bannerLabel.Text = SPSO:GetAttribute("Banner") or ""
	bannerLabel.TextTransparency, bannerLabel.TextStrokeTransparency = 0, 0.2
	bannerLabel.TextSize = 120
	TweenService:Create(bannerLabel, TweenInfo.new(0.35, Enum.EasingStyle.Back), { TextSize = 96 }):Play()
	task.delay(1.8, function()
		TweenService:Create(bannerLabel, TweenInfo.new(0.6), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
	end)
end
SPSO:GetAttributeChangedSignal("BannerSeq"):Connect(function()
	if SPSO:GetAttribute("BannerSeq") ~= lastBanner then
		lastBanner = SPSO:GetAttribute("BannerSeq")
		showBanner()
	end
end)

local function updateHUD()
	local char = player.Character
	local hum = char and char:FindFirstChildOfClass("Humanoid")
	if hum then hpFill.Size = UDim2.fromScale(math.clamp(hum.Health / math.max(1, hum.MaxHealth), 0, 1), 1) end
	local power = player:GetAttribute("SPSO_Power") or 0
	pwFill.Size = UDim2.fromScale(math.clamp(power / Config.SuperCost, 0, 1), 1)
	pwLabel.Text = power >= Config.SuperCost and "SUPER READY — press F" or "POWER"
	local w = SPSO:GetAttribute("Wave")
	waveLabel.Text = w and string.format("WAVE %d / %d   •   RIVALS LEFT %d", w, SPSO:GetAttribute("Waves") or 0, SPSO:GetAttribute("EnemiesLeft") or 0) or ""
	for model, hb in healthBars do
		local h = model:FindFirstChildOfClass("Humanoid")
		if h then
			hb.fill.Size = UDim2.fromScale(math.clamp(h.Health / math.max(1, h.MaxHealth), 0, 1), 1)
			hb.gui.Enabled = h.Health > 0
		end
	end
end

-- hit effects ------------------------------------------------------------------------------------------------
FxRemote.OnClientEvent:Connect(function(kind, data)
	if kind ~= "hit" then return end
	local spark = Instance.new("Part")
	spark.Shape = Enum.PartType.Ball
	spark.Material = Enum.Material.Neon
	spark.Color = data.team == "Hero" and Color3.fromRGB(255, 90, 90) or Color3.fromRGB(255, 230, 120)
	spark.Anchored, spark.CanCollide, spark.CanQuery, spark.CanTouch, spark.CastShadow = true, false, false, false, false
	spark.Size = Vector3.one * 1.5
	spark.Position = data.pos
	spark.Parent = workspace
	TweenService:Create(spark, TweenInfo.new(0.25), { Size = Vector3.one * (data.heavy and 7 or 4.5), Transparency = 1 }):Play()
	game:GetService("Debris"):AddItem(spark, 0.3)
	local bb = Instance.new("BillboardGui")
	bb.Size = UDim2.fromOffset(120, 50)
	bb.StudsOffsetWorldSpace = Vector3.new(math.random() * 2 - 1, 1, 0)
	bb.AlwaysOnTop = true
	local holder = Instance.new("Attachment")
	holder.WorldPosition = data.pos
	holder.Parent = workspace.Terrain
	bb.Adornee = holder
	local t = label(bb, tostring(data.amount), UDim2.fromScale(1, 1), UDim2.new(), data.heavy and 40 or 30,
		data.team == "Hero" and Color3.fromRGB(255, 110, 110) or Color3.fromRGB(255, 240, 150))
	bb.Parent = gui
	TweenService:Create(bb, TweenInfo.new(0.8), { StudsOffsetWorldSpace = bb.StudsOffsetWorldSpace + Vector3.new(0, 4, 0) }):Play()
	TweenService:Create(t, TweenInfo.new(0.8), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
	task.delay(0.85, function()
		bb:Destroy()
		holder:Destroy()
	end)
	if data.heavy then shake = math.max(shake, 0.9) end
end)

-- frame loop -------------------------------------------------------------------------------------------------
RunService.PreRender:Connect(function(dt)
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
	updateLocal()
	updateCamera(dt)
	updateHUD()
end)
