-- SPSO social zones, client: the original social camera (a fixed boom behind the hero, zoom between the zone's
-- "zoom" and "forward" booms), the zone's ambient light, the zone HUD after the original gameworld HUD (zone name;
-- the player frame with the hero's portrait, level and name - click the portrait to change hero - and the shop
-- button), the zone chooser, the player's own daily pickups (fractals, hero tokens, the golden fractal: the server
-- picks the spots and checks the pickups) with the original daily counter notifications, and the props' star pops.
-- Active while the player's zone is a hub zone.
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local Lighting = game:GetService("Lighting")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local Net = require(Game:WaitForChild("Net"))
local Sound = require(Game:WaitForChild("Sound"))
local Assets = require(Game:WaitForChild("Assets"))
local HubData = Config.HubData
if not HubData or Config.Mode ~= "Hub" then return end
local HubRemote = Net.event("Hub")
local player = Players.LocalPlayer
local camera = workspace.CurrentCamera
local G = Assets.Gui
local E = Config.Economy
local FONT = Enum.Font.FredokaOne
local NAVY, GOLD = Color3.fromRGB(24, 46, 96), Color3.fromRGB(255, 209, 81)

local function zone()
	local z = player:GetAttribute("SPSO_Zone")
	return z and HubData.Zones[z] and z or nil
end

-- HUD -----------------------------------------------------------------------------------------------------------------
local gui = Instance.new("ScreenGui")
gui.Name = "SPSO_Hub"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = true
gui.DisplayOrder = 3
gui.Enabled = false
gui.Parent = player:WaitForChild("PlayerGui")
local uiScale = Instance.new("UIScale")
uiScale.Parent = gui
local function rescale()
	local v = camera.ViewportSize
	uiScale.Scale = math.clamp(math.min(v.X / 1280, v.Y / 720), 0.55, 1.4)
end
rescale()
camera:GetPropertyChangedSignal("ViewportSize"):Connect(rescale)

local function label(parent, text, size, pos, color, z)
	local t = Instance.new("TextLabel")
	t.BackgroundTransparency = 1
	t.Size, t.Position = size, pos
	t.Font = FONT
	t.TextScaled = true
	t.TextColor3 = color or Color3.new(1, 1, 1)
	t.TextStrokeTransparency = 0.25
	t.Text = text
	t.ZIndex = z or 2
	t.Parent = parent
	return t
end
local function img(parent, key, size, pos, z)
	local i = Instance.new("ImageLabel")
	i.BackgroundTransparency = 1
	i.Image = G[key] or ""
	i.Size, i.Position = size, pos or UDim2.new()
	i.ScaleType = Enum.ScaleType.Fit
	i.ZIndex = z or 2
	i.Parent = parent
	return i
end
local function artButton(parent, base, size, pos, z)
	local b = Instance.new("ImageButton")
	b.BackgroundTransparency = 1
	b.Image = G[base .. "_normal"] or ""
	b.HoverImage = G[base .. "_highlight"] or b.Image
	b.PressedImage = G[base .. "_pressed"] or b.HoverImage
	b.ScaleType = Enum.ScaleType.Fit
	b.Size, b.Position = size, pos or UDim2.new()
	b.ZIndex = z or 3
	b.Parent = parent
	return b
end

local title = label(gui, "", UDim2.new(0, 520, 0, 40), UDim2.new(0.5, -260, 0, 12), Color3.fromRGB(255, 236, 140))
local msg = label(gui, "", UDim2.new(0, 640, 0, 36), UDim2.new(0.5, -320, 0.8, 0))
msg.TextTransparency, msg.TextStrokeTransparency = 1, 1
local function flash(text: string)
	msg.Text = text
	msg.TextTransparency, msg.TextStrokeTransparency = 0, 0.3
	task.delay(2.5, function()
		if msg.Text == text then
			TweenService:Create(msg, TweenInfo.new(0.5), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
		end
	end)
end

-- the player frame (bottom left): portrait (click: change hero), level, hero name; the shop button
local frame = img(gui, "world_hud_playerframe", UDim2.new(0, 277, 0, 163), UDim2.new(0, 10, 1, -170), 2)
local portrait = Instance.new("ImageButton")
portrait.BackgroundColor3 = Color3.fromRGB(40, 30, 20)
portrait.Size, portrait.Position = UDim2.new(0, 86, 0, 86), UDim2.new(0, 55, 0, 29)
portrait.ScaleType = Enum.ScaleType.Crop
portrait.ZIndex = 3
portrait.Parent = frame
Instance.new("UICorner", portrait).CornerRadius = UDim.new(1, 0)
local changeText = img(frame, "world_gameworld_portrait_text", UDim2.new(0, 128, 0, 128), UDim2.new(0, 34, 0, 66), 4)
changeText.Visible = false
local levelBg = img(frame, "world_hud_level_background", UDim2.new(0, 34, 0, 34), UDim2.new(0, 8, 0, 8), 4)
levelBg.ScaleType = Enum.ScaleType.Stretch
Instance.new("UICorner", levelBg).CornerRadius = UDim.new(1, 0)
local levelText = label(levelBg, "1", UDim2.new(0.8, 0, 0.8, 0), UDim2.new(0.1, 0, 0.1, 0), Color3.new(1, 1, 1), 5)
local heroName = label(frame, "", UDim2.new(0, 122, 0, 24), UDim2.new(0, 147, 0, 9), Color3.fromRGB(70, 40, 10), 4)
heroName.TextStrokeTransparency = 1
portrait.MouseEnter:Connect(function() changeText.Visible = true end)
portrait.MouseLeave:Connect(function() changeText.Visible = false end)
portrait.Activated:Connect(function()
	Sound.ui("click")
	if _G.SPSO_ShowSelect then _G.SPSO_ShowSelect() end
end)
local shopBtn = artButton(gui, "world_hud_shop", UDim2.new(0, 70, 0, 70), UDim2.new(0, 214, 1, -96), 3)
shopBtn.Activated:Connect(function()
	Sound.ui("click")
	if _G.SPSO_OpenStore then _G.SPSO_OpenStore() end
end)

-- daily counter notifications (the original DailyFractal / DailyToken / DailyGoldenFractal notifications) -------------
local notes = Instance.new("Frame")
notes.BackgroundTransparency = 1
notes.Size, notes.Position = UDim2.new(0, 240, 0, 300), UDim2.new(1, -256, 0, 112)
notes.Parent = gui
local nl = Instance.new("UIListLayout")
nl.Padding = UDim.new(0, 6)
nl.HorizontalAlignment = Enum.HorizontalAlignment.Right
nl.SortOrder = Enum.SortOrder.LayoutOrder
nl.Parent = notes
local noteSeq = 0
local function note(icon: string, text: string, sub: string?, subIcon: string?)
	noteSeq += 1
	local f = Instance.new("Frame")
	f.Size = UDim2.new(0, 230, 0, 70)
	f.BackgroundColor3 = NAVY
	f.BackgroundTransparency = 0.1
	f.LayoutOrder = noteSeq
	f.Parent = notes
	Instance.new("UICorner", f).CornerRadius = UDim.new(0, 14)
	local st = Instance.new("UIStroke")
	st.Color, st.Thickness = GOLD, 3
	st.Parent = f
	local ic = img(f, "", UDim2.new(0, 60, 0, 61), UDim2.new(0, 6, 0, 4), 3)
	ic.Image = icon
	local t = label(f, text, UDim2.new(0, 90, 0, 40), UDim2.new(0, 70, 0, 6), Color3.new(1, 1, 1), 3)
	t.TextXAlignment = Enum.TextXAlignment.Left
	if sub then
		local s = label(f, sub, UDim2.new(0, 110, 0, 22), UDim2.new(0, 70, 0, 44), GOLD, 3)
		s.TextXAlignment = Enum.TextXAlignment.Left
	end
	if subIcon then img(f, subIcon, UDim2.new(0, 70, 0, 46), UDim2.new(1, -74, 0, 12), 4) end
	f.Position = UDim2.new(0, 260, 0, 0)
	task.delay(3.2, function()
		for _, d in f:GetDescendants() do
			if d:IsA("TextLabel") then
				TweenService:Create(d, TweenInfo.new(0.4), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
			elseif d:IsA("ImageLabel") then
				TweenService:Create(d, TweenInfo.new(0.4), { ImageTransparency = 1 }):Play()
			elseif d:IsA("UIStroke") then
				TweenService:Create(d, TweenInfo.new(0.4), { Transparency = 1 }):Play()
			end
		end
		TweenService:Create(f, TweenInfo.new(0.4), { BackgroundTransparency = 1 }):Play()
		task.delay(0.45, function() f:Destroy() end)
	end)
end

-- zone chooser -------------------------------------------------------------------------------------------------------------
local zoneWin = Instance.new("Frame")
zoneWin.Size, zoneWin.Position = UDim2.new(0, 380, 0, 80), UDim2.new(0.5, -190, 0.5, -160)
zoneWin.BackgroundColor3 = NAVY
zoneWin.Visible = false
zoneWin.ZIndex = 10
zoneWin.Parent = gui
Instance.new("UICorner", zoneWin).CornerRadius = UDim.new(0, 16)
local zs = Instance.new("UIStroke")
zs.Color, zs.Thickness = GOLD, 3
zs.Parent = zoneWin
label(zoneWin, "Travel", UDim2.new(0, 240, 0, 36), UDim2.new(0, 20, 0, 10), GOLD, 11).TextXAlignment = Enum.TextXAlignment.Left
local zclose = artButton(zoneWin, "common_button_close", UDim2.new(0, 44, 0, 44), UDim2.new(1, -50, 0, 6), 12)
zclose.Activated:Connect(function()
	Sound.ui("windowOut")
	zoneWin.Visible = false
end)
local order = {}
for name, z in HubData.Zones do table.insert(order, { name = name, z = z }) end
table.sort(order, function(a, b) return a.z.order < b.z.order end)
table.insert(order, { name = "Brawler", z = { title = "Mission: Invader Ship" } })
zoneWin.Size = UDim2.new(0, 380, 0, 64 + #order * 52)
for i, e in order do
	local b = Instance.new("TextButton")
	b.Size, b.Position = UDim2.new(1, -40, 0, 44), UDim2.new(0, 20, 0, 56 + (i - 1) * 52)
	b.BackgroundColor3 = e.name == "Brawler" and Color3.fromRGB(200, 80, 40) or Color3.fromRGB(58, 96, 170)
	b.Font, b.TextScaled, b.TextColor3 = FONT, true, Color3.new(1, 1, 1)
	b.Text = e.z.title
	b.ZIndex = 11
	b.Parent = zoneWin
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 10)
	b.Activated:Connect(function()
		Sound.ui("click")
		zoneWin.Visible = false
		HubRemote:FireServer("travel", { zone = e.name })
	end)
end
_G.SPSO_OpenZones = function()
	Sound.ui("windowIn")
	zoneWin.Visible = true
end

-- the player's own daily pickups -------------------------------------------------------------------------------------------------
local pickupFolder = Instance.new("Folder")
pickupFolder.Name = "SPSO_MyPickups"
pickupFolder.Parent = workspace
local pickups = {} -- id -> part
local LOOK = {
	Fractal = { model = "Fractal", color = Color3.fromRGB(176, 104, 255), material = Enum.Material.Neon },
	Golden = { model = "Fractal", color = Color3.fromRGB(255, 200, 40), material = Enum.Material.Neon, scale = 1.35 },
	Token = { model = "HeroToken", color = Color3.fromRGB(255, 205, 60), material = Enum.Material.Metal },
}
local function clearPickups()
	for _, p in pickups do p:Destroy() end
	table.clear(pickups)
end
local function makePickup(c)
	local look = LOOK[c.kind]
	if not look then return end
	local lib = SPSO:FindFirstChild("HubPickups")
	local tpl = lib and lib:FindFirstChild(look.model)
	local p
	if tpl then
		p = tpl:Clone()
		p.TextureID = ""
	else
		p = Instance.new("Part")
		p.Size = Vector3.new(1.3, 2.2, 1.3)
	end
	if look.scale then p.Size *= look.scale end
	p.Name = c.kind
	p.Anchored, p.CanCollide, p.CanQuery, p.CanTouch, p.CastShadow = true, false, false, false, false
	p.Material, p.Color = look.material, look.color
	p.CFrame = CFrame.new(c.pos)
	p:SetAttribute("Base", c.pos)
	local light = Instance.new("PointLight")
	light.Color, light.Range, light.Brightness = look.color, c.kind == "Golden" and 12 or 8, 1.2
	light.Parent = p
	p.Parent = pickupFolder
	pickups[c.id] = p
end
local function pop(pos: Vector3, color: Color3)
	local s = Instance.new("Part")
	s.Anchored, s.CanCollide, s.CanQuery, s.CanTouch = true, false, false, false
	s.Material, s.Shape = Enum.Material.Neon, Enum.PartType.Ball
	s.Size, s.Position, s.Color = Vector3.one * 1.5, pos, color
	s.Parent = workspace
	TweenService:Create(s, TweenInfo.new(0.45), { Size = Vector3.one * 5, Transparency = 1, Position = pos + Vector3.new(0, 3, 0) }):Play()
	task.delay(0.5, function() s:Destroy() end)
end

HubRemote.OnClientEvent:Connect(function(kind, data)
	if kind == "pickups" then
		clearPickups()
		for _, c in data.list or {} do makePickup(c) end
	elseif kind == "collect" then
		local p = pickups[data.id]
		if p then
			p:Destroy()
			pickups[data.id] = nil
		end
		pop(data.pos, LOOK[data.kind] and LOOK[data.kind].color or Color3.new(1, 1, 1))
		local info = data.ok and data.info
		if not info then return end
		if data.kind == "Fractal" then
			Sound.ui("star")
			note(G.common_fractal or "", string.format("%d/%d", info.count, info.max), "Fractals")
		elseif data.kind == "Golden" then
			Sound.ui("coins")
			note(G.common_golden_fractal or "", "1/1", string.format("+%d Fractals", info.fractals))
		elseif data.kind == "Token" then
			Sound.ui("coins")
			note(G["hero_" .. (info.hero or "")] or "", string.format("%d/%d", info.count, info.max),
				string.format("+%d XP", info.xp), "world_game_world_xp_gain_icon")
			if info.levelUp then
				Sound.ui("levelUp")
				note(G.common_levelup_star or "", "Level " .. info.levelUp .. "!", "Level up!")
			end
		end
	elseif kind == "star" then -- a star pops out of a poked prop and fades
		Sound.ui("star")
		local lib = SPSO:FindFirstChild("HubPickups")
		local tpl = lib and lib:FindFirstChild("Star")
		if not tpl then return end
		local star = tpl:Clone()
		star.Anchored, star.CanCollide, star.CanQuery, star.CanTouch = true, false, false, false
		star.TextureID, star.Material, star.Color = "", Enum.Material.Neon, Color3.fromRGB(150, 230, 255)
		star.CFrame = CFrame.new(data.pos)
		star.Parent = workspace
		TweenService:Create(star, TweenInfo.new(0.9, Enum.EasingStyle.Quad, Enum.EasingDirection.Out),
			{ CFrame = CFrame.new(data.pos + Vector3.new(0, 5, 0)) * CFrame.Angles(0, math.pi * 3, 0), Transparency = 1 }):Play()
		task.delay(1, function() star:Destroy() end)
	elseif kind == "zones" then
		_G.SPSO_OpenZones()
	elseif kind == "message" then
		flash(data.text)
	elseif kind == "zone" then
		local z = HubData.Zones[data.zone]
		if z then flash(z.title) end
	end
end)

-- light and music per zone ---------------------------------------------------------------------------------------------------
local applied
local function applyZone(z, name)
	if applied == name then return end
	applied = name
	if not z then return end
	local a = z.ambient or { 0.6, 0.55, 0.75 }
	Lighting.Ambient = Color3.new(a[1], a[2], a[3]):Lerp(Color3.new(1, 1, 1), 0.35)
	Lighting.OutdoorAmbient = Color3.fromRGB(150, 150, 165)
	Lighting.Brightness = 2.4
	Lighting.ClockTime = 14
	Lighting.GlobalShadows = true
	Lighting.EnvironmentDiffuseScale = 0.5
	title.Text = z.title
	Sound.music(Config.Music.select)
end

-- social camera -----------------------------------------------------------------------------------------------------------------
local zoom, focus = 1, nil
UserInputService.InputChanged:Connect(function(input, gp)
	if not gp and input.UserInputType == Enum.UserInputType.MouseWheel and zone() then
		zoom = math.clamp(zoom - input.Position.Z * 0.1, Config.Hub.cameraZoom[1], Config.Hub.cameraZoom[2])
	end
end)

RunService:BindToRenderStep("SPSO_HubCamera", Enum.RenderPriority.Camera.Value + 2, function(dt)
	local zn = zone()
	gui.Enabled = zn ~= nil and player.Character ~= nil
	pickupFolder.Parent = zn and workspace or nil
	if not zn then
		applied = nil
		zoneWin.Visible = false
		return
	end
	local z = HubData.Zones[zn]
	applyZone(z, zn)
	local hero = player:GetAttribute("SPSO_Hero")
	local h = hero and Config.Heroes[hero]
	heroName.Text = h and h.displayName or ""
	portrait.Image = hero and G["hero_" .. hero] or ""
	levelText.Text = tostring(player:GetAttribute("SPSO_Level") or 1)
	local t = os.clock()
	local i = 0
	for _, c in pickups do
		i += 1
		local base = c:GetAttribute("Base") or c.Position
		c.CFrame = CFrame.new(base + Vector3.new(0, math.sin(t * 2 + i) * 0.3, 0)) * CFrame.Angles(0, t * 2.2, 0)
	end
	local char = player.Character
	local hrp = char and char:FindFirstChild("HumanoidRootPart")
	if not hrp then return end
	local cam = z.camera or {}
	local fwd = cam.boomForward or { dir = { 0, 0.5, -0.86 }, distance = 36 }
	local zm = cam.boomZoom or fwd
	local dir = Vector3.new(fwd.dir[1], fwd.dir[2], fwd.dir[3]):Lerp(Vector3.new(zm.dir[1], zm.dir[2], zm.dir[3]), math.clamp(1 - zoom, 0, 1)).Unit
	local dist = fwd.distance * zoom
	local target = hrp.Position + Vector3.new(0, 2.5, 0)
	focus = focus and focus:Lerp(target, 1 - math.exp(-8 * dt)) or target
	camera.CameraType = Enum.CameraType.Scriptable
	camera.FieldOfView = cam.fov or 45
	camera.CFrame = CFrame.lookAt(focus + dir * dist, focus)
end)
