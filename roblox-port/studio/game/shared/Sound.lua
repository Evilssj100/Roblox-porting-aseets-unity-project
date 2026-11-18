-- Plays the original game's sounds from the one uploaded sound sprite (tools/build_fx.py packs every hero
-- sound, UI sound and music track into one file; FxData.Sounds holds each clip's [start, length]).
--   Sound.play(key, { at = Instance | Vector3 | nil, volume, pitch, minDist, maxDist })  -> Sound?
--   Sound.music(key)  loops a track (nil stops the music)
local SoundService = game:GetService("SoundService")
local Debris = game:GetService("Debris")

local Game = script.Parent
local FxData = require(Game:WaitForChild("FxData"))
local Assets = require(Game:WaitForChild("Assets"))

local Sound = {}
local SEGMENTS = FxData.Sounds or {}
Sound.Volume = { sfx = 0.8, ui = 0.6, music = 0.35 }

local function make(key: string, opts)
	local seg = SEGMENTS[key]
	if not seg or Assets.SoundSprite == "" then return nil end
	local s = Instance.new("Sound")
	s.Name = key
	s.SoundId = Assets.SoundSprite
	s.PlaybackRegionsEnabled = true
	s.PlaybackRegion = NumberRange.new(seg[1], seg[1] + seg[2])
	s.PlaybackSpeed = opts.pitch or 1
	s.Volume = (opts.volume or 1) * (opts.channel and Sound.Volume[opts.channel] or Sound.Volume.sfx)
	s.RollOffMode = Enum.RollOffMode.InverseTapered
	s.RollOffMinDistance = opts.minDist or 10
	s.RollOffMaxDistance = math.max(opts.maxDist or 200, (opts.minDist or 10) + 1)
	return s, seg[2] / (opts.pitch or 1)
end

function Sound.has(key: string): boolean
	return SEGMENTS[key] ~= nil
end

function Sound.play(key: string, opts)
	opts = opts or {}
	local s, length = make(key, opts)
	if not s then return nil end
	local at = opts.at
	if typeof(at) == "Vector3" then
		local a = Instance.new("Attachment")
		a.WorldPosition = at
		a.Parent = workspace.Terrain
		s.Parent = a
		Debris:AddItem(a, length + 0.3)
	elseif typeof(at) == "Instance" then
		s.Parent = at
		Debris:AddItem(s, length + 0.3)
	else
		s.Parent = SoundService
		Debris:AddItem(s, length + 0.3)
	end
	s:Play()
	return s
end

local current
function Sound.music(key: string?)
	if current then
		current:Stop()
		current:Destroy()
		current = nil
	end
	if not key then return end
	local s = make(key, { channel = "music" })
	if not s then return end
	s.Looped = true
	s.LoopRegion = s.PlaybackRegion
	s.Parent = SoundService
	s:Play()
	current = s
end

-- UI helpers: the original HUD sounds
function Sound.ui(name: string)
	local map = {
		click = "HUD_UI_Button_Press_Small", clickBig = "HUD_UI_Button_Press_Large",
		hover = "HUD_UI_Button_Rollover_Small_" .. math.random(1, 4), windowIn = "HUD_UI_GlobalWindowIn",
		windowOut = "HUD_UI_GlobalWindowOut", alert = "HUD_UI_Popup_Alert", achievement = "HUD_UI_EarnAchievement",
		levelUp = "HUD_UI_LevelUp", coins = "HUD_UI_EarnCoins", xp = "HUD_UI_EarnXP", star = "FX_Pickups_Star_Collect10",
		whoosh = "HUD_UI_CameraWhoosh", tab = "HUD_UI_Shop_Tab", win = "HUD_UI_PrizeWheel_Win", lose = "HUD_UI_PrizeWheel_Lose",
		spawn = "Fx_Spawn_Char_SpawnIn_1",
	}
	return Sound.play(map[name] or name, { channel = "ui" })
end

return Sound
