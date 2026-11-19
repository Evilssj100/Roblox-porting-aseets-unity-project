-- SPSO hub menus, after the original's GlobalNav, ShoppingWindow and backpack:
--   * the global nav (top right): fractal and gold totals on the original bar art, the drop-down toggle and the
--     original nav buttons (Shop, Mission, Travel, Achievements, Crafting, Cards, Backpack, Arcade, Friends, Settings)
--   * the store: left nav categories (StoreData), item grid with tags (New!, Owned!, Coming Soon), detail panel with
--     the original BUY FOR buttons (gold, fractals), purchase confirmation, the original store messages
--   * the backpack: owned potions (use), titles and medallions (equip), heroes and badges
--   * every hero's billboard (title + player name) and potion looks (Highlight overlays)
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local SPSO = ReplicatedStorage:WaitForChild("SPSO")
local Game = SPSO:WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local Net = require(Game:WaitForChild("Net"))
local Sound = require(Game:WaitForChild("Sound"))
local Assets = require(Game:WaitForChild("Assets"))
local StoreData = require(Game:WaitForChild("StoreData"))
if not Config.HubData or Config.Mode ~= "Hub" then return end
local ShopFunc = Net.func("Shop")
local ProfileRemote = Net.event("Profile")
local HubRemote = Net.event("Hub")
local player = Players.LocalPlayer
local G = Assets.Gui
local profile = { gold = 0, fractals = 0, owned = {}, heroes = {} }

local FONT = Enum.Font.FredokaOne
local NAVY, NAVY2, GOLD = Color3.fromRGB(24, 46, 96), Color3.fromRGB(36, 72, 140), Color3.fromRGB(255, 209, 81)

local function img(parent, key, size, pos, z)
	local i = Instance.new("ImageLabel")
	i.BackgroundTransparency = 1
	i.Image = G[key] or ""
	i.Size, i.Position = size, pos or UDim2.new()
	i.ZIndex = z or 2
	i.ScaleType = Enum.ScaleType.Fit
	i.Parent = parent
	return i
end
local function text(parent, s, size, pos, color, z)
	local t = Instance.new("TextLabel")
	t.BackgroundTransparency = 1
	t.Size, t.Position = size, pos or UDim2.new()
	t.Font, t.TextScaled = FONT, true
	t.TextColor3 = color or Color3.new(1, 1, 1)
	t.TextStrokeTransparency = 0.35
	t.Text = s
	t.ZIndex = z or 3
	t.Parent = parent
	return t
end
local function panel(parent, size, pos, color, z)
	local f = Instance.new("Frame")
	f.Size, f.Position = size, pos or UDim2.new()
	f.BackgroundColor3 = color or NAVY
	f.ZIndex = z or 1
	f.Parent = parent
	Instance.new("UICorner", f).CornerRadius = UDim.new(0, 14)
	local s = Instance.new("UIStroke")
	s.Color, s.Thickness = GOLD, 3
	s.Parent = f
	return f
end
-- an image button with the original normal / highlight / pressed art
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

local function itemName(it): string
	if it.name then return it.name end
	local h = it.hero and Config.Heroes[it.hero]
	local hn = h and h.displayName or it.hero or "?"
	if it.kind == "hero" then return hn end
	if it.kind == "badge" then return hn .. (it.level == 2 and "'s Gold Badge" or "'s Silver Badge") end
	if it.kind == "medallion" then return "Favorite Hero: " .. hn end
	return it.id
end
local function owns(it): boolean
	if it.kind == "hero" then return profile.heroes[it.hero] == true end
	return (profile.owned[it.id] or 0) > 0
end
local UNIQUE = { hero = true, badge = true, title = true, medallion = true, sidekick = true }

local gui = Instance.new("ScreenGui")
gui.Name = "SPSO_Menus"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = true
gui.DisplayOrder = 5
gui.Parent = player:WaitForChild("PlayerGui")
local scale = Instance.new("UIScale")
scale.Parent = gui
local function rescale()
	local v = workspace.CurrentCamera.ViewportSize
	scale.Scale = math.clamp(math.min(v.X / 1280, v.Y / 720), 0.55, 1.4)
end
rescale()
workspace.CurrentCamera:GetPropertyChangedSignal("ViewportSize"):Connect(rescale)

-- toast (the original notification panel) -----------------------------------------------------------------------------
local toast = text(gui, "", UDim2.new(0, 640, 0, 40), UDim2.new(0.5, -320, 0.86, 0), Color3.new(1, 1, 1), 20)
toast.TextTransparency, toast.TextStrokeTransparency = 1, 1
local function say(s: string)
	toast.Text = s
	toast.TextTransparency, toast.TextStrokeTransparency = 0, 0.3
	local stamp = os.clock()
	toast:SetAttribute("Stamp", stamp)
	task.delay(2.6, function()
		if toast:GetAttribute("Stamp") == stamp then
			TweenService:Create(toast, TweenInfo.new(0.4), { TextTransparency = 1, TextStrokeTransparency = 1 }):Play()
		end
	end)
end

-- global nav -------------------------------------------------------------------------------------------------------------
local nav = Instance.new("Frame")
nav.BackgroundTransparency = 1
nav.Size, nav.Position = UDim2.new(0, 260, 0, 90), UDim2.new(1, -278, 0, 12)
nav.Parent = gui
local bar = img(nav, "hud_globalnav_bg", UDim2.new(0, 210, 0, 85), UDim2.new(0, 0, 0, 0), 2)
bar.ScaleType = Enum.ScaleType.Stretch
img(nav, "hud_fractal_icon", UDim2.new(0, 26, 0, 30), UDim2.new(0, 146, 0, 12), 3)
img(nav, "hud_gold_icon", UDim2.new(0, 30, 0, 28), UDim2.new(0, 144, 0, 46), 3)
local fractalLabel = text(nav, "0", UDim2.new(0, 120, 0, 26), UDim2.new(0, 18, 0, 13), Color3.fromRGB(80, 40, 110), 3)
local goldLabel = text(nav, "0", UDim2.new(0, 120, 0, 26), UDim2.new(0, 18, 0, 47), Color3.fromRGB(120, 80, 0), 3)
for _, l in { fractalLabel, goldLabel } do
	l.TextXAlignment = Enum.TextXAlignment.Right
	l.TextStrokeTransparency = 1
end
local toggle = Instance.new("ImageButton")
toggle.BackgroundTransparency = 1
toggle.Size, toggle.Position = UDim2.new(0, 70, 0, 70), UDim2.new(0, 188, 0, 6)
toggle.Image, toggle.HoverImage = G.hud_button_drop_down_normal or "", G.hud_button_drop_down_highlight or ""
toggle.PressedImage = G.hud_button_drop_down_pressed or ""
toggle.ZIndex = 4
toggle.Parent = nav

local navList = Instance.new("Frame")
navList.BackgroundTransparency = 1
navList.Size, navList.Position = UDim2.new(0, 260, 0, 0), UDim2.new(0, 0, 0, 92)
navList.AutomaticSize = Enum.AutomaticSize.Y
navList.Visible = false
navList.Parent = nav
local layout = Instance.new("UIListLayout")
layout.Padding = UDim.new(0, 4)
layout.HorizontalAlignment = Enum.HorizontalAlignment.Right
layout.Parent = navList

local openStore, openBackpack -- defined below
local NAV_BUTTONS = {
	{ "Go to the Shop", "hud_globalnav_store", function() openStore() end },
	{ "Play a Mission", "hud_globalnav_mission", function() HubRemote:FireServer("travel", { zone = "Brawler" }) end },
	{ "Travel", "hud_globalnav_explore", function() if _G.SPSO_OpenZones then _G.SPSO_OpenZones() end end },
	{ "View Achievements", "hud_globalnav_achievements" },
	{ "Craft Items", "hud_globalnav_craft" },
	{ "Play a Card Game", "hud_globalnav_cards" },
	{ "Open Your Backpack", "hud_globalnav_inventory", function() openBackpack() end },
	{ "Play an Arcade Game", "hud_globalnav_arcade" },
	{ "View Your Friends", "hud_globalnav_friends" },
	{ "Game Settings", "hud_globalnav_settings" },
}
for i, def in NAV_BUTTONS do
	local b = Instance.new("TextButton")
	b.AutoButtonColor = true
	b.Size = UDim2.new(0, 250, 0, 40)
	b.BackgroundColor3 = NAVY2
	b.Text = ""
	b.LayoutOrder = i
	b.ZIndex = 5
	b.Parent = navList
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 12)
	local st = Instance.new("UIStroke")
	st.Color, st.Thickness = GOLD, 2
	st.Parent = b
	img(b, def[2], UDim2.new(0, 38, 0, 38), UDim2.new(0, 4, 0, 1), 6)
	local l = text(b, def[1], UDim2.new(1, -52, 0, 26), UDim2.new(0, 46, 0, 7), Color3.new(1, 1, 1), 6)
	l.TextXAlignment = Enum.TextXAlignment.Left
	b.Activated:Connect(function()
		Sound.ui("click")
		navList.Visible = false
		toggle.Image = G.hud_button_drop_down_normal or ""
		if def[3] then def[3]() else say("Coming soon!") end
	end)
end
toggle.Activated:Connect(function()
	Sound.ui("click")
	navList.Visible = not navList.Visible
	local k = navList.Visible and "hud_button_drop_down_on" or "hud_button_drop_down"
	toggle.Image, toggle.HoverImage = G[k .. "_normal"] or "", G[k .. "_highlight"] or ""
	toggle.PressedImage = G[k .. "_pressed"] or ""
end)

-- modal windows ----------------------------------------------------------------------------------------------------------
local modal = Instance.new("TextButton") -- dims and blocks the world behind a window
modal.Size, modal.BackgroundColor3, modal.BackgroundTransparency = UDim2.fromScale(1, 1), Color3.new(0, 0, 0), 0.45
modal.Text, modal.AutoButtonColor, modal.Visible, modal.ZIndex = "", false, false, 9
modal.Parent = gui
local function window(w: number, h: number, title: string?)
	local f = panel(gui, UDim2.new(0, w, 0, h), UDim2.new(0.5, -w / 2, 0.5, -h / 2), NAVY, 10)
	f.Visible = false
	local close = artButton(f, "common_button_close", UDim2.new(0, 48, 0, 48), UDim2.new(1, -40, 0, -10), 14)
	close.Activated:Connect(function()
		Sound.ui("windowOut")
		f.Visible, modal.Visible = false, false
	end)
	if title then text(f, title, UDim2.new(0, 400, 0, 40), UDim2.new(0, 20, 0, 8), GOLD, 12).TextXAlignment = Enum.TextXAlignment.Left end
	return f
end
local function show(f)
	for _, c in gui:GetChildren() do
		if c:IsA("Frame") and c ~= nav and c:GetAttribute("Window") then c.Visible = false end
	end
	f:SetAttribute("Window", true)
	f.Visible, modal.Visible = true, true
	Sound.ui("windowIn")
end

-- store ------------------------------------------------------------------------------------------------------------------
local storeWin = window(980, 600)
storeWin:SetAttribute("Window", true)
local TAB_ART = { new = "shop_tabtitle_special", heroes = "shop_tabtitle_heroes", badges = "shop_tabtitle_badges",
	missions = "shop_tabtitle_missions", sidekicks = "shop_tabtitle_sidekicks", potions = "shop_tabtitle_goodies",
	cards = "shop_tabtitle_cards", crafts = "shop_tabtitle_more", mystery = "shop_tabtitle_more", titles = "shop_tabtitle_more",
	gear = "shop_tabtitle_hq", misc = "shop_tabtitle_more", medallions = "shop_tabtitle_more", bundles = "shop_tabtitle_special" }
local tabArt = img(storeWin, "shop_tabtitle_heroes", UDim2.new(0, 240, 0, 70), UDim2.new(0, 200, 0, -34), 13)
local goldDisplay = img(storeWin, "shop_gold_display", UDim2.new(0, 150, 0, 62), UDim2.new(1, -460, 0, 2), 12)
local goldDisplayLabel = text(goldDisplay, "0", UDim2.new(0.5, 0, 0.42, 0), UDim2.new(0.45, 0, 0.5, 0), Color3.fromRGB(120, 80, 0), 13)
goldDisplayLabel.TextStrokeTransparency = 1
img(storeWin, "hud_fractal_icon", UDim2.new(0, 26, 0, 30), UDim2.new(1, -300, 0, 18), 12)
local fractalDisplayLabel = text(storeWin, "0", UDim2.new(0, 90, 0, 28), UDim2.new(1, -270, 0, 19), Color3.fromRGB(230, 200, 255), 12)
fractalDisplayLabel.TextXAlignment = Enum.TextXAlignment.Left
local buyGold = artButton(storeWin, "shop_button_buygold_shoppingpopup", UDim2.new(0, 160, 0, 62), UDim2.new(1, -205, 0, 4), 12)
buyGold.ImageRectOffset, buyGold.ImageRectSize = Vector2.new(16, 86), Vector2.new(226, 86) -- the button inside its 256 canvas
buyGold.Activated:Connect(function() say("Gold will be sold in the store soon!") end)

local left = panel(storeWin, UDim2.new(0, 190, 1, -84), UDim2.new(0, 12, 0, 72), NAVY2, 11)
local leftList = Instance.new("ScrollingFrame")
leftList.BackgroundTransparency = 1
leftList.Size, leftList.Position = UDim2.new(1, -8, 1, -10), UDim2.new(0, 4, 0, 5)
leftList.ScrollBarThickness, leftList.AutomaticCanvasSize, leftList.CanvasSize = 4, Enum.AutomaticSize.Y, UDim2.new()
leftList.ZIndex = 12
leftList.Parent = left
local ll = Instance.new("UIListLayout")
ll.Padding = UDim.new(0, 4)
ll.Parent = leftList

local center = panel(storeWin, UDim2.new(0, 470, 1, -84), UDim2.new(0, 210, 0, 72), Color3.fromRGB(16, 30, 66), 11)
local grid = Instance.new("ScrollingFrame")
grid.BackgroundTransparency = 1
grid.Size, grid.Position = UDim2.new(1, -12, 1, -12), UDim2.new(0, 6, 0, 6)
grid.ScrollBarThickness, grid.AutomaticCanvasSize, grid.CanvasSize = 6, Enum.AutomaticSize.Y, UDim2.new()
grid.ZIndex = 12
grid.Parent = center
local gl = Instance.new("UIGridLayout")
gl.CellSize, gl.CellPadding = UDim2.new(0, 142, 0, 172), UDim2.new(0, 8, 0, 8)
gl.SortOrder = Enum.SortOrder.LayoutOrder
gl.Parent = grid
local emptyLabel = text(center, "Restocking In Progress - Please Check Back Later!", UDim2.new(1, -40, 0, 30), UDim2.new(0, 20, 0.45, 0), GOLD, 13)

local detail = panel(storeWin, UDim2.new(0, 278, 1, -84), UDim2.new(1, -290, 0, 72), NAVY2, 11)
local dIcon = img(detail, "", UDim2.new(0, 150, 0, 150), UDim2.new(0.5, -75, 0, 14), 12)
local dName = text(detail, "", UDim2.new(1, -24, 0, 34), UDim2.new(0, 12, 0, 170), GOLD, 12)
local dDesc = text(detail, "", UDim2.new(1, -24, 0, 92), UDim2.new(0, 12, 0, 206), Color3.new(1, 1, 1), 12)
dDesc.TextScaled, dDesc.TextWrapped, dDesc.TextSize = false, true, 17
dDesc.TextYAlignment = Enum.TextYAlignment.Top
local dOwned = img(detail, "shop_owned_indicator", UDim2.new(0, 70, 0, 64), UDim2.new(1, -78, 0, 8), 13)
local dSoon = img(detail, "shop_coming_soon_burst", UDim2.new(0, 110, 0, 86), UDim2.new(0, 8, 0, 8), 13)
local buyG = artButton(detail, "shop_buybutton_gold", UDim2.new(0, 130, 0, 130), UDim2.new(0, 6, 1, -150), 12)
local buyF = artButton(detail, "shop_buybutton_silver", UDim2.new(0, 130, 0, 130), UDim2.new(1, -136, 1, -150), 12)
local buyGLabel = text(buyG, "", UDim2.new(0.42, 0, 0.17, 0), UDim2.new(0.42, 0, 0.47, 0), Color3.fromRGB(110, 70, 0), 13)
local buyFLabel = text(buyF, "", UDim2.new(0.42, 0, 0.17, 0), UDim2.new(0.42, 0, 0.47, 0), Color3.fromRGB(90, 60, 120), 13)
buyGLabel.TextStrokeTransparency, buyFLabel.TextStrokeTransparency = 1, 1
img(buyF, "hud_fractal_icon", UDim2.new(0.2, 0, 0.2, 0), UDim2.new(0.2, 0, 0.45, 0), 14) -- fractals, not silver coins
local dStatus = text(detail, "", UDim2.new(1, -24, 0, 26), UDim2.new(0, 12, 1, -34), Color3.new(1, 1, 1), 12)

local currentNav, selected, navButtons = "new", nil, {}
local refreshGrid -- forward
local function select(id)
	selected = id
	local it = id and StoreData.items[id]
	detail.Visible = it ~= nil
	if not it then return end
	dIcon.Image = G[it.icon or ""] or ""
	dName.Text = itemName(it)
	dDesc.Text = it.desc or ""
	local own = UNIQUE[it.kind] and owns(it)
	dOwned.Visible = own
	dSoon.Visible = it.soon == true
	local canG = not it.soon and not own and (it.gold or 0) > 0
	local canF = not it.soon and not own and (it.fractals or 0) > 0
	buyG.Visible, buyF.Visible = canG, canF
	buyGLabel.Text, buyFLabel.Text = tostring(it.gold or ""), tostring(it.fractals or "")
	local count = profile.owned[it.id]
	dStatus.Text = own and (it.kind == "hero" and "You own this Hero." or "You already own this!")
		or (count and count > 0 and ("You have " .. count .. ".")) or (it.kind == "hero" and "Buy This Hero!" or "")
end

-- purchase confirmation (the original asked before spending)
local confirm = panel(gui, UDim2.new(0, 420, 0, 190), UDim2.new(0.5, -210, 0.5, -95), NAVY, 30)
confirm.Visible = false
local cText = text(confirm, "", UDim2.new(1, -30, 0, 70), UDim2.new(0, 15, 0, 16), Color3.new(1, 1, 1), 31)
local cYes = artButton(confirm, "shop_slideview_buy", UDim2.new(0, 150, 0, 90), UDim2.new(0, 40, 1, -100), 31)
text(cYes, "BUY!", UDim2.new(0.5, 0, 0.28, 0), UDim2.new(0.25, 0, 0.36, 0), Color3.fromRGB(30, 90, 20), 32).TextStrokeTransparency = 1
local cNo = artButton(confirm, "shop_adspace_nobutton", UDim2.new(0, 150, 0, 90), UDim2.new(1, -190, 1, -100), 31)
local pending
local function ask(id, currency)
	local it = StoreData.items[id]
	pending = { id = id, currency = currency }
	cText.Text = string.format("Buy %s for %d %s?", itemName(it), it[currency], currency == "gold" and "Gold" or "Fractals")
	confirm.Visible = true
end
cNo.Activated:Connect(function() confirm.Visible, pending = false, nil end)
cYes.Activated:Connect(function()
	local p = pending
	confirm.Visible, pending = false, nil
	if not p then return end
	local ok, res = pcall(function() return ShopFunc:InvokeServer("buy", p.id, p.currency) end)
	if not ok or type(res) ~= "table" then
		say("The store is busy, try again!")
		return
	end
	if res.profile then profile = res.profile end
	if res.ok then
		Sound.ui("coins")
		say("Purchase Complete.  Congratulations!!!")
	else
		Sound.ui("alert")
		say(res.msg or "Purchase failed")
	end
	refreshGrid()
	select(p.id)
end)
buyG.Activated:Connect(function() if selected then ask(selected, "gold") end end)
buyF.Activated:Connect(function() if selected then ask(selected, "fractals") end end)

local function card(it, order)
	local b = Instance.new("TextButton")
	b.AutoButtonColor = true
	b.Text = ""
	b.BackgroundColor3 = Color3.fromRGB(46, 86, 160)
	b.LayoutOrder = order
	b.ZIndex = 13
	b.Parent = grid
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 12)
	local st = Instance.new("UIStroke")
	st.Color, st.Thickness = it.id == selected and Color3.fromRGB(255, 255, 255) or GOLD, it.id == selected and 4 or 2
	st.Parent = b
	img(b, it.icon or "", UDim2.new(0, 96, 0, 96), UDim2.new(0.5, -48, 0, 8), 14)
	local n = text(b, itemName(it), UDim2.new(1, -10, 0, 22), UDim2.new(0, 5, 0, 106), Color3.new(1, 1, 1), 14)
	n.TextStrokeTransparency = 0.5
	local row = Instance.new("Frame")
	row.BackgroundTransparency = 1
	row.Size, row.Position = UDim2.new(1, -10, 0, 30), UDim2.new(0, 5, 0, 134)
	row.ZIndex = 14
	row.Parent = b
	if (it.gold or 0) > 0 then
		img(row, "hud_gold_icon", UDim2.new(0, 24, 0, 24), UDim2.new(0, 2, 0, 3), 15)
		text(row, tostring(it.gold), UDim2.new(0, 40, 0, 22), UDim2.new(0, 28, 0, 4), GOLD, 15).TextXAlignment = Enum.TextXAlignment.Left
	end
	if (it.fractals or 0) > 0 then
		img(row, "hud_fractal_icon", UDim2.new(0, 20, 0, 24), UDim2.new(0.5, 4, 0, 3), 15)
		text(row, tostring(it.fractals), UDim2.new(0, 50, 0, 22), UDim2.new(0.5, 26, 0, 4), Color3.fromRGB(230, 200, 255), 15).TextXAlignment = Enum.TextXAlignment.Left
	end
	if UNIQUE[it.kind] and owns(it) then
		img(b, "shop_tag_owned", UDim2.new(0, 58, 0, 50), UDim2.new(1, -60, 0, 2), 16)
	elseif it.soon then
		img(b, "shop_coming_soon_burst", UDim2.new(0, 62, 0, 48), UDim2.new(0, 0, 0, 0), 16)
	elseif currentNav == "new" then
		img(b, "shop_tag_new", UDim2.new(0, 64, 0, 50), UDim2.new(0, -4, 0, -4), 16)
	end
	b.Activated:Connect(function()
		Sound.ui("click")
		select(it.id)
		refreshGrid()
	end)
end

refreshGrid = function()
	for _, c in grid:GetChildren() do
		if c:IsA("GuiObject") then c:Destroy() end
	end
	local ids = StoreData.byNav[currentNav] or {}
	emptyLabel.Visible = #ids == 0
	for i, id in ids do card(StoreData.items[id], i) end
	goldDisplayLabel.Text = tostring(profile.gold or 0)
	fractalDisplayLabel.Text = tostring(profile.fractals or 0)
	for id, b in navButtons do
		b.BackgroundColor3 = id == currentNav and Color3.fromRGB(70, 120, 210) or NAVY
	end
end

for i, n in StoreData.nav do
	local b = Instance.new("TextButton")
	b.Size = UDim2.new(1, -6, 0, 36)
	b.BackgroundColor3 = NAVY
	b.Text = ""
	b.LayoutOrder = i
	b.ZIndex = 13
	b.Parent = leftList
	Instance.new("UICorner", b).CornerRadius = UDim.new(0, 10)
	local c = n.color and Color3.fromRGB(n.color[1], n.color[2], n.color[3]) or Color3.fromRGB(120, 190, 255)
	local l = text(b, n.title, UDim2.new(1, -14, 0, 24), UDim2.new(0, 8, 0, 6), n.soon and Color3.fromRGB(140, 150, 170) or c, 14)
	l.TextXAlignment = Enum.TextXAlignment.Left
	navButtons[n.id] = b
	b.Activated:Connect(function()
		Sound.ui("tab")
		currentNav = n.id
		tabArt.Image = G[TAB_ART[n.id] or "shop_tabtitle_more"] or ""
		local first = (StoreData.byNav[n.id] or {})[1]
		select(first)
		refreshGrid()
		if n.soon then say("Coming soon!") end
	end)
end

openStore = function()
	navList.Visible = false
	show(storeWin)
	tabArt.Image = G[TAB_ART[currentNav]] or ""
	select(selected or (StoreData.byNav[currentNav] or {})[1])
	refreshGrid()
end
_G.SPSO_OpenStore = function() openStore() end

-- backpack ---------------------------------------------------------------------------------------------------------------
local pack = window(760, 520, "Backpack")
img(pack, "world_daily_reward_tickets_1", UDim2.new(0, 40, 0, 34), UDim2.new(1, -230, 0, 10), 12)
local ticketLabel = text(pack, "0 Tickets", UDim2.new(0, 160, 0, 28), UDim2.new(1, -186, 0, 13), Color3.new(1, 1, 1), 12)
ticketLabel.TextXAlignment = Enum.TextXAlignment.Left
local packList = Instance.new("ScrollingFrame")
packList.BackgroundTransparency = 1
packList.Size, packList.Position = UDim2.new(1, -24, 1, -64), UDim2.new(0, 12, 0, 54)
packList.ScrollBarThickness, packList.AutomaticCanvasSize, packList.CanvasSize = 6, Enum.AutomaticSize.Y, UDim2.new()
packList.ZIndex = 12
packList.Parent = pack
local pl = Instance.new("UIListLayout")
pl.Padding = UDim.new(0, 6)
pl.SortOrder = Enum.SortOrder.LayoutOrder
pl.Parent = packList
local refreshPack
local function act(action, id, kind)
	local ok, res = pcall(function() return ShopFunc:InvokeServer(action, id, kind) end)
	if ok and type(res) == "table" then
		if res.profile then profile = res.profile end
		if res.msg then say(res.msg) end
	end
	refreshPack()
end
refreshPack = function()
	for _, c in packList:GetChildren() do
		if c:IsA("GuiObject") then c:Destroy() end
	end
	ticketLabel.Text = string.format("%d Tickets", profile.tickets or 0)
	local rows = {}
	for h in profile.heroes or {} do
		local it = StoreData.items["hero_" .. h]
		if it then table.insert(rows, { it = it, order = 1 }) end
	end
	for id, n in profile.owned or {} do
		local it = StoreData.items[id]
		if it and n > 0 then
			table.insert(rows, { it = it, n = n, order = ({ potion = 2, title = 3, medallion = 4, badge = 5 })[it.kind] or 6 })
		end
	end
	table.sort(rows, function(a, b)
		if a.order ~= b.order then return a.order < b.order end
		return itemName(a.it) < itemName(b.it)
	end)
	for i, r in rows do
		local it = r.it
		local row = panel(packList, UDim2.new(1, -10, 0, 58), UDim2.new(), NAVY2, 13)
		row.LayoutOrder = i
		img(row, it.icon or "", UDim2.new(0, 50, 0, 50), UDim2.new(0, 6, 0, 4), 14)
		local n = text(row, itemName(it) .. (r.n and r.n > 1 and ("  x" .. r.n) or ""), UDim2.new(0.6, 0, 0, 28), UDim2.new(0, 66, 0, 15), Color3.new(1, 1, 1), 14)
		n.TextXAlignment = Enum.TextXAlignment.Left
		local verb, fn
		if it.kind == "potion" then
			verb, fn = "Use", function() act("use", it.id) end
		elseif it.kind == "title" or it.kind == "medallion" then
			local on = profile[it.kind] == it.id
			verb = on and "Remove" or "Equip"
			fn = function() act("equip", (not on) and it.id or nil, it.kind) end
		end
		if verb then
			local b = Instance.new("TextButton")
			b.Size, b.Position = UDim2.new(0, 120, 0, 40), UDim2.new(1, -130, 0, 9)
			b.BackgroundColor3 = verb == "Remove" and Color3.fromRGB(180, 70, 60) or Color3.fromRGB(70, 170, 60)
			b.Font, b.TextScaled, b.TextColor3, b.Text = FONT, true, Color3.new(1, 1, 1), verb
			b.ZIndex = 15
			b.Parent = row
			Instance.new("UICorner", b).CornerRadius = UDim.new(0, 10)
			b.Activated:Connect(function()
				Sound.ui("click")
				fn()
			end)
		end
	end
end
openBackpack = function()
	navList.Visible = false
	show(pack)
	refreshPack()
end

-- daily reward (the original DAILY REWARD! panel: 8 days, consecutive logins move along the track) ---------------------
local daily = img(gui, "world_dailyreward_mainpanel", UDim2.new(0, 506, 0, 409), UDim2.new(0.5, -253, 0.5, -205), 20)
daily.Visible = false
daily.ScaleType = Enum.ScaleType.Stretch
local SLOT_X, SLOT_Y = { 8, 97, 186, 274 }, { 55, 155 } -- slot corners in the 361 x 292 panel art
local K = 506 / 361
local REWARD_ICON = { fractals = { "world_daily_reward_silver_", { 25, 75, 225 } },
	tickets = { "world_daily_reward_tickets_", { 5, 10, 15, 30 } }, gold = { "world_daily_reward_gold_", { 5, 50, 500 } } }
local slots = {}
for i = 1, 8 do
	local x, y = SLOT_X[(i - 1) % 4 + 1] * K, SLOT_Y[math.floor((i - 1) / 4) + 1] * K
	-- the glow sits behind today's slot (a sibling: a child always draws over its parent)
	local glow = img(daily, "world_dailyreward_panel_today_fx1", UDim2.new(0, 83 * K * 1.5, 0, 94 * K * 1.4),
		UDim2.new(0, x - 83 * K * 0.25, 0, y - 94 * K * 0.2), 20)
	local s = img(daily, "world_dailyreward_panel_unclaimed", UDim2.new(0, 83 * K, 0, 94 * K), UDim2.new(0, x, 0, y), 21)
	s.ScaleType = Enum.ScaleType.Stretch
	local icon = img(s, "", UDim2.new(0.8, 0, 0.5, 0), UDim2.new(0.1, 0, 0.2, 0), 23)
	local amount = text(s, "", UDim2.new(0.9, 0, 0.2, 0), UDim2.new(0.05, 0, 0.74, 0), Color3.new(1, 1, 1), 24)
	local dayLabel = img(s, "world_dailyreward_label_day" .. i, UDim2.new(0, 60 * K * 0.9, 0, 46 * K * 0.9), UDim2.new(0, -10, 0, -14), 25)
	local sash = img(s, "world_dailyreward_panel_collected_background", UDim2.new(1, 0, 1, 0), UDim2.new(), 26)
	sash.ScaleType = Enum.ScaleType.Stretch
	local done = text(s, "Collected!", UDim2.new(0.95, 0, 0.18, 0), UDim2.new(0.02, 0, 0.42, 0), Color3.fromRGB(255, 255, 210), 27)
	done.Rotation = -32
	slots[i] = { s = s, glow = glow, icon = icon, amount = amount, day = dayLabel, sash = sash, done = done }
end
local dailyText = text(daily, "", UDim2.new(0, 330, 0, 30), UDim2.new(0, 22, 0, 361), Color3.new(1, 1, 1), 22)
dailyText.TextXAlignment = Enum.TextXAlignment.Left
local dailyOk = artButton(daily, "world_ok", UDim2.new(0, 96, 0, 96), UDim2.new(1, -70, 1, -84), 23)
local dailyShown, dailyBusy = nil, false
local function untilTomorrow(): string
	local now = os.time()
	local left = 86400 - now % 86400
	return string.format("%d:%02d:%02d", left // 3600, (left % 3600) // 60, left % 60)
end
local function drawDaily(collected: boolean)
	local login = profile.login or {}
	local slot = login.slot or 1
	for i, sl in slots do
		local r = (login.track or {})[i]
		local kind, n = r and r[1], r and r[2]
		local ic = kind and REWARD_ICON[kind]
		local tier = 1
		if ic then
			for k, v in ic[2] do
				if n >= v then tier = k end
			end
			sl.icon.Image = G[ic[1] .. tier] or ""
		end
		sl.amount.Text = n and tostring(n) or ""
		local past, today = i < slot or (i == slot and collected), i == slot
		sl.s.Image = (today and not collected) and (G.world_dailyreward_panel_today or "") or (G.world_dailyreward_panel_unclaimed or "")
		sl.glow.Visible = today and not collected
		sl.sash.Visible, sl.done.Visible = past, past
		sl.day.Image = (today and G.world_dailyreward_label_today) or G["world_dailyreward_label_day" .. i] or ""
	end
	dailyText.Text = collected and ("Next reward in " .. untilTomorrow())
		or "Here's your reward for logging in today!"
end
local function showDaily()
	drawDaily(false)
	daily.Visible, modal.Visible = true, true
	Sound.ui("windowIn")
end
dailyOk.Activated:Connect(function()
	if dailyBusy then return end
	if not (profile.login and profile.login.pending) then
		daily.Visible, modal.Visible = false, false
		return
	end
	dailyBusy = true
	local ok, res = pcall(function() return ShopFunc:InvokeServer("claimDaily") end)
	dailyBusy = false
	if ok and type(res) == "table" then
		if res.profile then profile = res.profile end
		if res.ok and res.reward then
			Sound.ui("coins")
			local names = { fractals = "Fractals", tickets = "Tickets", gold = "Gold" }
			say(string.format("+%d %s", res.reward[2], names[res.reward[1]] or res.reward[1]))
		elseif res.msg then
			say(res.msg)
		end
	end
	drawDaily(true)
	fractalLabel.Text, goldLabel.Text = tostring(profile.fractals or 0), tostring(profile.gold or 0)
	task.delay(1.6, function()
		if daily.Visible then
			daily.Visible = false
			if not (storeWin.Visible or pack.Visible) then modal.Visible = false end
		end
	end)
end)

-- profile updates --------------------------------------------------------------------------------------------------------------
local function applyProfile(p)
	if type(p) ~= "table" then return end
	profile = p
	fractalLabel.Text, goldLabel.Text = tostring(p.fractals or 0), tostring(p.gold or 0)
	if storeWin.Visible then
		refreshGrid()
		select(selected)
	end
	if pack.Visible then refreshPack() end
	-- the daily reward shows once a day, when the hero is in a social zone
	local day = os.date("!%Y-%m-%d")
	if p.login and p.login.pending and dailyShown ~= day then
		task.spawn(function()
			while not (player:GetAttribute("SPSO_Zone") and Config.HubData.Zones[player:GetAttribute("SPSO_Zone")] and player.Character) do
				task.wait(0.5)
			end
			if dailyShown == day then return end
			dailyShown = day
			showDaily()
		end)
	end
end
ProfileRemote.OnClientEvent:Connect(applyProfile)
task.spawn(function()
	local ok, res = pcall(function() return ShopFunc:InvokeServer("profile") end)
	if ok and type(res) == "table" and res.profile then applyProfile(res.profile) end
end)
HubRemote.OnClientEvent:Connect(function(kind)
	if kind == "openStore" then openStore() end
end)

-- the hub menus show only in the social zones
RunService.Heartbeat:Connect(function()
	local z = player:GetAttribute("SPSO_Zone")
	local inHub = z ~= nil and Config.HubData.Zones[z] ~= nil and player.Character ~= nil
	nav.Visible = inHub
	if not inHub and (storeWin.Visible or pack.Visible or daily.Visible) then
		storeWin.Visible, pack.Visible, modal.Visible, confirm.Visible, daily.Visible = false, false, false, false, false
	end
end)

-- billboards (title + name, the original PlayerBillboard) and potion looks on every hero -----------------------------------
local decorated = {}
local POTION_LOOK = {
	material = function(e) return Color3.new(e.color[1], e.color[2], e.color[3]), 0.15, e.transparency or 0 end,
	tint = function(e) return Color3.new(e.color[1], e.color[2], e.color[3]), 0.1, e.transparency or 0 end,
	fade = function(e) return Color3.new(0.85, 0.95, 1), 0.85, e.transparency or 0.85 end,
}
local function decorate(model: Model)
	local st = decorated[model]
	if not st then
		st = {}
		decorated[model] = st
		local hrp = model:FindFirstChild("HumanoidRootPart")
		if not hrp then return end
		local bb = Instance.new("BillboardGui")
		bb.Name = "SPSO_Billboard"
		bb.Size = UDim2.new(0, 220, 0, 52)
		bb.StudsOffset = Vector3.new(0, 4.2, 0)
		bb.AlwaysOnTop, bb.MaxDistance, bb.LightInfluence = false, 90, 0
		bb.Parent = hrp
		st.title = text(bb, "", UDim2.new(1, 0, 0.42, 0), UDim2.new(), GOLD, 2)
		st.name = text(bb, "", UDim2.new(1, 0, 0.5, 0), UDim2.new(0, 0, 0.46, 0), Color3.new(1, 1, 1), 2)
		st.bb = bb
	end
	if not st.bb or not st.bb.Parent then return end
	st.name.Text = model:GetAttribute("SPSO_Player") or ""
	st.title.Text = model:GetAttribute("SPSO_Title") or ""
	st.bb.Enabled = st.name.Text ~= ""
	-- potion look
	local pid = model:GetAttribute("SPSO_Potion")
	local it = pid and StoreData.items[pid]
	local eff = it and it.effect
	if (pid or "") ~= (st.potion or "") then
		st.potion = pid
		if st.hl then st.hl:Destroy() st.hl = nil end
		for p, t in st.fade or {} do
			if p.Parent then p.LocalTransparencyModifier = t end
		end
		st.fade = nil
		if eff and POTION_LOOK[eff.type] then
			local color, fill, fade = POTION_LOOK[eff.type](eff)
			if eff.type ~= "fade" then
				local hl = Instance.new("Highlight")
				hl.FillColor, hl.FillTransparency = color, fill
				hl.OutlineTransparency = 1
				hl.DepthMode = Enum.HighlightDepthMode.Occluded
				hl.Parent = model
				st.hl = hl
			end
			if fade > 0 then
				st.fade = {}
				for _, p in model:GetDescendants() do
					if p:IsA("BasePart") and p.Name ~= "HumanoidRootPart" then
						st.fade[p] = p.LocalTransparencyModifier
					end
				end
			end
			st.fadeAmount = fade
		end
	end
	if st.fade then
		for p in st.fade do
			if p.Parent then p.LocalTransparencyModifier = math.max(p.LocalTransparencyModifier, st.fadeAmount) end
		end
	end
end
RunService.RenderStepped:Connect(function()
	for _, m in CollectionService:GetTagged("SPSO_Fighter") do
		if m:IsA("Model") and m:GetAttribute("SPSO_Player") then decorate(m) end
	end
	for m in decorated do
		if not m.Parent then decorated[m] = nil end
	end
end)
