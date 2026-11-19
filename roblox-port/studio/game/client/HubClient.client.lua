-- SPSO social zones, client: the original social camera (a fixed boom behind the hero, zoom between the zone's
-- "zoom" and "forward" booms), the zone's ambient light, the hub HUD (zone name, fractals, hero tokens, stars,
-- zone travel), collectible spin and pickup pops. Active while the player's zone is a hub zone.
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local Lighting = game:GetService("Lighting")
local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local Net = require(Game:WaitForChild("Net"))
local Sound = require(Game:WaitForChild("Sound"))
local HubData = Config.HubData
if not HubData or Config.Mode ~= "Hub" then return end
local HubRemote = Net.event("Hub")
local player = Players.LocalPlayer
local camera = workspace.CurrentCamera

local function zone()
	local z = player:GetAttribute("SPSO_Zone")
	return z and HubData.Zones[z] and z or nil
end

-- HUD -----------------------------------------------------------------------------------------------------------------
local gui = Instance.new("ScreenGui")
gui.Name = "SPSO_Hub"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = true
gui.Enabled = false
gui.Parent = player:WaitForChild("PlayerGui")
local function label(parent, text, size, pos, color)
	local t = Instance.new("TextLabel")
	t.BackgroundTransparency = 1
	t.Size, t.Position = size, pos
	t.Font = Enum.Font.FredokaOne
	t.TextScaled = true
	t.TextColor3 = color or Color3.new(1, 1, 1)
	t.TextStrokeTransparency = 0.25
	t.Text = text
	t.Parent = parent
	return t
end
local title = label(gui, "", UDim2.new(0.4, 0, 0.055, 0), UDim2.new(0.3, 0, 0.02, 0), Color3.fromRGB(255, 236, 140))
local bar = Instance.new("Frame")
bar.Size, bar.Position = UDim2.new(0, 330, 0, 54), UDim2.new(0, 16, 1, -70)
bar.BackgroundColor3 = Color3.fromRGB(28, 40, 74)
bar.BackgroundTransparency = 0.15
bar.Parent = gui
Instance.new("UICorner", bar).CornerRadius = UDim.new(0, 14)
local counts = {}
for i, k in { "Fractals", "Tokens", "Stars" } do
	local icon = Instance.new("Frame")
	icon.Size, icon.Position = UDim2.new(0, 26, 0, 26), UDim2.new(0, 14 + (i - 1) * 105, 0.5, -13)
	icon.BackgroundColor3 = ({ Color3.fromRGB(176, 104, 255), Color3.fromRGB(255, 205, 60), Color3.fromRGB(150, 230, 255) })[i]
	icon.Rotation = i == 1 and 45 or 0
	icon.Parent = bar
	Instance.new("UICorner", icon).CornerRadius = UDim.new(i == 1 and 0 or 1, 0)
	counts[k] = label(bar, "0", UDim2.new(0, 60, 0, 32), UDim2.new(0, 46 + (i - 1) * 105, 0.5, -16))
	counts[k].TextXAlignment = Enum.TextXAlignment.Left
end
local zonesBtn = Instance.new("TextButton")
zonesBtn.Size, zonesBtn.Position = UDim2.new(0, 120, 0, 44), UDim2.new(1, -136, 1, -64)
zonesBtn.BackgroundColor3 = Color3.fromRGB(240, 150, 40)
zonesBtn.Font, zonesBtn.TextScaled = Enum.Font.FredokaOne, true
zonesBtn.TextColor3, zonesBtn.Text = Color3.new(1, 1, 1), "ZONES"
zonesBtn.Parent = gui
Instance.new("UICorner", zonesBtn).CornerRadius = UDim.new(0, 12)
local msg = label(gui, "", UDim2.new(0.5, 0, 0.05, 0), UDim2.new(0.25, 0, 0.8, 0))
msg.TextTransparency, msg.TextStrokeTransparency = 1, 1

local menu = Instance.new("Frame")
menu.Size, menu.Position = UDim2.new(0, 300, 0, 60), UDim2.new(1, -316, 1, -140)
menu.BackgroundColor3 = Color3.fromRGB(28, 40, 74)
menu.Visible = false
menu.Parent = gui
Instance.new("UICorner", menu).CornerRadius = UDim.new(0, 14)
local list = Instance.new("UIListLayout")
list.Padding = UDim.new(0, 6)
list.Parent = menu
local order = {}
for name, z in HubData.Zones do table.insert(order, { name = name, z = z }) end
table.sort(order, function(a, b) return a.z.order < b.z.order end)
table.insert(order, { name = "Brawler", z = { title = "Mission: Invader Ship" } })
menu.Size = UDim2.new(0, 300, 0, #order * 50 + 10)
menu.Position = UDim2.new(1, -316, 1, -76 - #order * 50 - 10)
for _, e in order do
	local b = Instance.new("TextButton")
	b.Size = UDim2.new(1, -12, 0, 44)
	b.BackgroundColor3 = Color3.fromRGB(58, 96, 170)
	b.Font, b.TextScaled, b.TextColor3 = Enum.Font.FredokaOne, true, Color3.new(1, 1, 1)
	b.Text = e.z.title
	b.Parent = menu
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 10)
	b.Activated:Connect(function()
		menu.Visible = false
		HubRemote:FireServer("travel", { zone = e.name })
	end)
end
zonesBtn.Activated:Connect(function() menu.Visible = not menu.Visible end)

local function flash(text: string)
	msg.Text = text
	msg.TextTransparency, msg.TextStrokeTransparency = 0, 0.3
	task.delay(2.5, function()
		if msg.Text == text then
			TweenService:Create(msg, TweenInfo.new(0.5), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
		end
	end)
end

HubRemote.OnClientEvent:Connect(function(kind, data)
	if kind == "collect" then
		Sound.ui("FX_Pickups_Generic_Collect")
		local pop = Instance.new("Part")
		pop.Anchored, pop.CanCollide, pop.CanQuery = true, false, false
		pop.Material, pop.Shape = Enum.Material.Neon, Enum.PartType.Ball
		pop.Size, pop.Position = Vector3.one * 1.5, data.pos
		pop.Color = data.kind == "Fractal" and Color3.fromRGB(176, 104, 255) or Color3.fromRGB(255, 205, 60)
		pop.Parent = workspace
		TweenService:Create(pop, TweenInfo.new(0.45), { Size = Vector3.one * 5, Transparency = 1, Position = data.pos + Vector3.new(0, 3, 0) }):Play()
		task.delay(0.5, function() pop:Destroy() end)
	elseif kind == "zones" then
		menu.Visible = true
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
	if not zn then
		applied = nil
		return
	end
	local z = HubData.Zones[zn]
	applyZone(z, zn)
	for k, l in counts do l.Text = tostring(player:GetAttribute("SPSO_" .. k) or 0) end
	for _, c in CollectionService:GetTagged("SPSO_Collectible") do
		c.CFrame = CFrame.new(c.Position) * CFrame.Angles(0, os.clock() * 2.2, c.Name == "Fractal" and 0.6 or math.pi / 2)
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
