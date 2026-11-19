-- SPSO economy, after the original's profile, shopping and inventory services:
--   * the player profile (gold, fractals, owned items, owned heroes, equipped title and medallion) kept in a DataStore
--     (session-only when the place has no API access, e.g. Studio without "Enable Studio Access to API Services")
--   * store purchases (StoreData, tools/convert_store.py): gold or fractal price, unique items owned once, fractal
--     bags, badges in order; the backpack: equip titles and medallions, use potions (their effect shows on the hero)
--   * the daily pickups of the social zones (original shs_activities): per hero and day 10 fractals (1 fractal
--     each), one golden fractal (10 fractals) and 5 hero tokens (XP 40/60/80/120/200 by count, plus fractals for
--     the squad); hero XP and levels (original level chart)
--   * the daily login reward: the original 8-day track (fractals, tickets, gold), consecutive days advance it
-- Clients: RemoteFunction "Shop" (profile / buy / equip / use / claimDaily), RemoteEvent "Profile" (pushes),
-- player attributes SPSO_Gold, SPSO_Fractals, SPSO_Tickets, SPSO_Title, SPSO_Medallion, SPSO_Level; characters
-- carry SPSO_Title, SPSO_Medallion, SPSO_Level, SPSO_Potion.
local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Game = ReplicatedStorage:WaitForChild("SPSO"):WaitForChild("Game")
local Config = require(Game:WaitForChild("GameConfig"))
local Net = require(Game:WaitForChild("Net"))
local StoreData = require(Game:WaitForChild("StoreData"))
local E = Config.Economy
local ShopFunc = Net.func("Shop")
local ProfileRemote = Net.event("Profile")

local ds
local dsOk = pcall(function() ds = DataStoreService:GetDataStore(E.dataStore) end)
local profiles, dirty = {}, {}
local warned = false

local function today(): string
	return os.date("!%Y-%m-%d") :: string
end
local function dayNumber(): number
	return math.floor(os.time() / 86400)
end

-- the original level chart (XP at which each level starts) and daily login track (track 1)
local LEVELS = { 0, 100, 400, 900, 1600, 2500, 3600, 4900, 6400, 8100, 10000, 12000, 14500, 17000, 20000, 23000, 27000,
	31000, 35000, 40000, 45000, 50000, 55000, 60000, 66000, 72000, 79000, 86000, 93000, 100000, 108000, 116000, 125000,
	134000, 144000, 154000, 165000, 176000, 188000, 200000 }
local DAILY_TRACK = { { "fractals", 25 }, { "fractals", 75 }, { "fractals", 225 }, { "tickets", 5 }, { "tickets", 10 },
	{ "tickets", 15 }, { "tickets", 30 }, { "gold", 5 } }
local TOKEN_XP = { 40, 60, 80, 120, 200 }
local function levelOf(xp: number): number
	local lv = 1
	for i, start in LEVELS do
		if xp >= start then lv = i end
	end
	return lv
end

local function default()
	local heroes = {}
	for _, it in StoreData.items do
		if it.kind == "hero" and it.starter then heroes[it.hero] = true end
	end
	return { v = 1, gold = E.startGold, fractals = E.startFractals, tickets = 0, owned = {}, heroes = heroes, title = nil,
		medallion = nil, xp = {}, daily = { day = "", heroes = {} }, login = { day = "", streak = 0, claimed = "" } }
end

local function load(player: Player)
	local p = default()
	if dsOk and ds then
		local okGet, data
		for attempt = 1, 3 do
			okGet, data = pcall(function() return ds:GetAsync("u_" .. player.UserId) end)
			if okGet then break end
			task.wait(attempt)
		end
		if okGet and type(data) == "table" then
			for k, v in data do p[k] = v end
		elseif not okGet then
			p.sessionOnly = true
			if not warned then
				warned = true
				warn("[SPSO] profiles are session-only (DataStore unavailable): " .. tostring(data))
			end
		end
	else
		p.sessionOnly = true
	end
	for h in default().heroes do p.heroes[h] = true end -- starter heroes are always owned
	profiles[player] = p
	return p
end

local function save(player: Player)
	local p = profiles[player]
	if not p or p.sessionOnly or not dirty[player] or not ds then return end
	dirty[player] = nil
	local copy = table.clone(p)
	copy.sessionOnly = nil
	local okSet, err = pcall(function()
		ds:UpdateAsync("u_" .. player.UserId, function() return copy end)
	end)
	if not okSet then
		dirty[player] = true
		warn("[SPSO] profile save failed: " .. tostring(err))
	end
end

-- consecutive days advance the login track; a missed day starts it again
local function loginDay(p)
	local t = today()
	if p.login.day == t then return end
	local yesterday = os.date("!%Y-%m-%d", os.time() - 86400)
	p.login.streak = p.login.day == yesterday and (p.login.streak or 0) + 1 or 1
	p.login.day = t
end
local function loginSlot(p): number
	return ((math.max(1, p.login.streak or 1) - 1) % #DAILY_TRACK) + 1
end

local function snapshot(p)
	local levels = {}
	for h, xp in p.xp do levels[h] = levelOf(xp) end
	return { gold = p.gold, fractals = p.fractals, tickets = p.tickets, owned = p.owned, heroes = p.heroes,
		title = p.title, medallion = p.medallion, xp = p.xp, levels = levels, sessionOnly = p.sessionOnly,
		login = { slot = loginSlot(p), streak = p.login.streak, pending = p.login.claimed ~= today(), track = DAILY_TRACK } }
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

local function decorate(player: Player)
	local p, char = profiles[player], player.Character
	if not p then return end
	player:SetAttribute("SPSO_Gold", p.gold)
	player:SetAttribute("SPSO_Fractals", p.fractals)
	player:SetAttribute("SPSO_Tickets", p.tickets)
	local title = p.title and StoreData.items[p.title]
	local medal = p.medallion and StoreData.items[p.medallion]
	local hero = player:GetAttribute("SPSO_Hero")
	local level = hero and levelOf(p.xp[hero] or 0) or nil
	player:SetAttribute("SPSO_Title", title and itemName(title) or nil)
	player:SetAttribute("SPSO_Medallion", medal and itemName(medal) or nil)
	player:SetAttribute("SPSO_Level", level)
	if char then
		char:SetAttribute("SPSO_Title", title and itemName(title) or nil)
		char:SetAttribute("SPSO_Medallion", medal and itemName(medal) or nil)
		char:SetAttribute("SPSO_Level", level)
		char:SetAttribute("SPSO_Player", player.DisplayName)
	end
end

local function push(player: Player)
	local p = profiles[player]
	if not p then return end
	decorate(player)
	ProfileRemote:FireClient(player, snapshot(p))
end

local function changed(player: Player)
	dirty[player] = true
	push(player)
end

-- purchases ------------------------------------------------------------------------------------------------------------
local UNIQUE = { hero = true, badge = true, title = true, medallion = true, sidekick = true }
local function owns(p, it): boolean
	if it.kind == "hero" then return p.heroes[it.hero] == true end
	return (p.owned[it.id] or 0) > 0
end

local function buy(player: Player, id, currency)
	local p, it = profiles[player], type(id) == "string" and StoreData.items[id]
	if not p or not it then return { ok = false, msg = "That item isn't in the store." } end
	if it.soon then return { ok = false, msg = "Coming soon!" } end
	if currency ~= "gold" and currency ~= "fractals" then currency = "gold" end
	local price = it[currency]
	if type(price) ~= "number" or price <= 0 then
		return { ok = false, msg = currency == "fractals" and "This item can only be bought with Gold." or "This item can only be bought with Fractals." }
	end
	if UNIQUE[it.kind] and owns(p, it) then return { ok = false, msg = "You already own " .. itemName(it) .. "." } end
	if it.requires and not owns(p, StoreData.items[it.requires]) then
		return { ok = false, msg = "Buy " .. itemName(StoreData.items[it.requires]) .. " first." }
	end
	if p[currency] < price then
		return { ok = false, msg = currency == "gold" and "You don't have enough Gold." or "You don't have enough Fractals.", short = currency }
	end
	p[currency] -= price
	if it.kind == "hero" then
		p.heroes[it.hero] = true
	elseif it.kind == "moneybag" then
		p.fractals += it.grant or 0
	else
		p.owned[it.id] = (p.owned[it.id] or 0) + (it.qty or 1)
	end
	changed(player)
	return { ok = true, msg = itemName(it) .. (it.kind == "moneybag" and " opened!" or " purchased!"), profile = snapshot(p) }
end

local function equip(player: Player, id, kind)
	local p = profiles[player]
	if not p then return { ok = false } end
	if id == nil then -- unequip
		if kind == "title" then p.title = nil elseif kind == "medallion" then p.medallion = nil end
		changed(player)
		return { ok = true, profile = snapshot(p) }
	end
	local it = type(id) == "string" and StoreData.items[id]
	if not it or not owns(p, it) then return { ok = false, msg = "You don't own that." } end
	if it.kind == "title" then p.title = id elseif it.kind == "medallion" then p.medallion = id else return { ok = false } end
	changed(player)
	return { ok = true, msg = itemName(it) .. " equipped!", profile = snapshot(p) }
end

local potionUntil = {}
local function use(player: Player, id)
	local p, it = profiles[player], type(id) == "string" and StoreData.items[id]
	if not p or not it or it.kind ~= "potion" then return { ok = false } end
	if (p.owned[id] or 0) <= 0 then return { ok = false, msg = "You don't have any left." } end
	local char = player.Character
	if not char or not it.effect then return { ok = false, msg = "You can't use that right now." } end
	p.owned[id] -= 1
	if p.owned[id] <= 0 then p.owned[id] = nil end
	char:SetAttribute("SPSO_Potion", id)
	local stamp = os.clock()
	potionUntil[player] = stamp
	task.delay(E.potionMinutes * 60, function()
		if potionUntil[player] == stamp and char.Parent and char:GetAttribute("SPSO_Potion") == id then
			char:SetAttribute("SPSO_Potion", nil)
		end
	end)
	changed(player)
	return { ok = true, msg = itemName(it) .. "!", profile = snapshot(p) }
end

-- the daily login reward: today's slot of the track, once a day
local function claimDaily(player: Player)
	local p = profiles[player]
	if not p then return { ok = false } end
	loginDay(p)
	if p.login.claimed == today() then return { ok = false, msg = "You already collected today's reward!", profile = snapshot(p) } end
	local r = DAILY_TRACK[loginSlot(p)]
	p.login.claimed = today()
	p[r[1]] = (p[r[1]] or 0) + r[2]
	changed(player)
	return { ok = true, reward = r, profile = snapshot(p) }
end

ShopFunc.OnServerInvoke = function(player, action, a, b)
	if not profiles[player] then return { ok = false, msg = "Loading your profile..." } end
	if action == "profile" then return { ok = true, profile = snapshot(profiles[player]) } end
	if action == "buy" then return buy(player, a, b) end
	if action == "equip" then return equip(player, a, b) end
	if action == "use" then return use(player, a) end
	if action == "claimDaily" then return claimDaily(player) end
	return { ok = false }
end

-- daily pickups: collection state per hero for today (bit masks: fractal and token indices, golden flag)
local function dailyOf(p, hero: string)
	if p.daily.day ~= today() then p.daily = { day = today(), heroes = {} } end
	local h = p.daily.heroes[hero]
	if not h then
		h = { f = 0, t = 0, g = false }
		p.daily.heroes[hero] = h
	end
	return h
end
local function bits(mask: number, n: number)
	local set, count = {}, 0
	for i = 1, n do
		if bit32.btest(mask, bit32.lshift(1, i - 1)) then
			set[i] = true
			count += 1
		end
	end
	return set, count
end

-- API for the other server scripts ---------------------------------------------------------------------------------------
_G.SPSO_Economy = {
	-- today's pickups for a hero: which fractal / token indices are collected, and the golden fractal
	dailyState = function(player: Player, hero: string)
		local p = profiles[player]
		if not p then return nil end
		local h = dailyOf(p, hero)
		local f, fc = bits(h.f, E.dailyFractals)
		local t, tc = bits(h.t, E.dailyTokens)
		return { day = today(), dayNumber = dayNumber(), fractal = f, fractalCount = fc, token = t, tokenCount = tc,
			golden = h.g == true }
	end,
	-- a pickup collected (Hub.server checks the spot): kind "Fractal" / "Token" (index) or "Golden"
	collectDaily = function(player: Player, hero: string, kind: string, index: number)
		local p = profiles[player]
		if not p then return false end
		local h = dailyOf(p, hero)
		local info
		if kind == "Fractal" or kind == "Token" then
			local key, max = kind == "Fractal" and "f" or "t", kind == "Fractal" and E.dailyFractals or E.dailyTokens
			if type(index) ~= "number" or index < 1 or index > max then return false end
			local bit = bit32.lshift(1, index - 1)
			if bit32.btest(h[key], bit) then return false end
			h[key] = bit32.bor(h[key], bit)
			local _, count = bits(h[key], max)
			if kind == "Fractal" then
				p.fractals += E.fractalValue
				info = { count = count, max = max, fractals = E.fractalValue }
			else
				local xp = TOKEN_XP[math.clamp(count, 1, #TOKEN_XP)]
				local before = levelOf(p.xp[hero] or 0)
				p.xp[hero] = (p.xp[hero] or 0) + xp
				p.fractals += E.tokenFractals
				info = { count = count, max = max, xp = xp, fractals = E.tokenFractals, hero = hero,
					levelUp = levelOf(p.xp[hero]) > before and levelOf(p.xp[hero]) or nil }
			end
		elseif kind == "Golden" then
			if h.g then return false end
			h.g = true
			p.fractals += E.goldenValue
			info = { count = 1, max = 1, fractals = E.goldenValue }
		else
			return false
		end
		changed(player)
		return true, info
	end,
	addFractals = function(player: Player, n: number)
		local p = profiles[player]
		if not p or n == 0 then return end
		p.fractals = math.max(0, p.fractals + n)
		changed(player)
	end,
	addGold = function(player: Player, n: number)
		local p = profiles[player]
		if not p or n == 0 then return end
		p.gold = math.max(0, p.gold + n)
		changed(player)
	end,
	ownsHero = function(player: Player, hero: string): boolean
		local p = profiles[player]
		if not p then return true end
		local starter = StoreData.items["hero_" .. hero]
		return p.heroes[hero] == true or starter == nil or starter.starter == true
	end,
	itemName = itemName,
}

-- lifecycle ----------------------------------------------------------------------------------------------------------------
local function onPlayer(player: Player)
	local p = load(player)
	loginDay(p)
	push(player)
	player.CharacterAdded:Connect(function()
		task.wait() -- the character's attributes are set after it is parented
		potionUntil[player] = nil
		decorate(player)
	end)
	player:GetAttributeChangedSignal("SPSO_Hero"):Connect(function() decorate(player) end)
end
Players.PlayerAdded:Connect(onPlayer)
for _, pl in Players:GetPlayers() do task.spawn(onPlayer, pl) end
Players.PlayerRemoving:Connect(function(player)
	save(player)
	profiles[player], dirty[player], potionUntil[player] = nil, nil, nil
end)
game:BindToClose(function()
	for player in profiles do task.spawn(save, player) end
	task.wait(2)
end)
task.spawn(function()
	while true do
		task.wait(E.autosaveSeconds)
		for player in profiles do task.spawn(save, player) end
	end
end)
-- a new day while playing: the login track moves on (the client shows the reward panel again)
task.spawn(function()
	while true do
		task.wait(30)
		for player, p in profiles do
			if p.login.day ~= today() then
				loginDay(p)
				changed(player)
			end
		end
	end
end)
