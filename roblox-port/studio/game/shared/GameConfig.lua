-- SPSO brawler tuning. Clip names, timings and events come from the original game's animations;
-- the numbers here (speeds, damage, waves) are the Roblox port's tuning.
local WM = { Once = 1, Loop = 2, PingPong = 4, ClampForever = 8 }

local Config = {}

Config.Map = "OrbitalArena"
Config.PlayerHero = "ElRugido"

Config.Heroes = {
	ElRugido = {
		displayName = "El Rugido",
		pack = "ElRugido",
		template = "Hero_ElRugido", -- ServerStorage.SPSO.Characters
		headPart = "ElRugido_Head",
		bodyPart = "ElRugido_Body",
		-- the 8 FacialAnimation expressions (Normal, Happy, Surprised, Aggressive, Squint, Blink, Custom1, Custom2)
		-- (tile 0 uses the model's own head texture, which is the same image)
		faceTextures = {
			"rbxassetid://95009761023746", "rbxassetid://87813758884419", "rbxassetid://129014191028706",
			"rbxassetid://80712657085550", "rbxassetid://125458260096839", "rbxassetid://121373604073448",
			"rbxassetid://123655553866245", "rbxassetid://126536608314547",
		},
		-- wrap modes the original CharacterMotionController / behaviours set
		wrapModes = {
			movement_idle = WM.Loop, movement_run = WM.Loop, pickup_idle = WM.Loop, pickup_run = WM.Loop,
			jump_fall_loop = WM.Loop, sit_idle = WM.Loop, emote_manipulate_loop = WM.Loop,
			jump_up = WM.ClampForever, jump_run_up = WM.ClampForever, jump_fall = WM.ClampForever,
			jump_run_fall = WM.ClampForever, jump_land = WM.ClampForever, jump_run_land = WM.ClampForever,
			recoil_death = WM.ClampForever, recoil_launch = WM.ClampForever, pickup = WM.ClampForever,
		},
		walkSpeed = 24, -- studs/s
		runAnimSpeed = 24, -- movement_run plays at 1x at this speed (scaled like the original)
		jumpPower = 62,
		health = 1000,
	},
}

-- chains: OnChainAttackAnimTag opens the window for the next attack (BehaviorAttackBase)
Config.Chains = {
	L = { "attack_L1", "attack_L2", "attack_L3", "attack_L4", "attack_L5" },
	R = { "attack_R1", "attack_R2", "attack_R3" },
	Super = { "attack_super" },
}

-- damage and the reaction the target plays
Config.Attacks = {
	attack_L1 = { damage = 32, reaction = "small" },
	attack_L2 = { damage = 36, reaction = "small" },
	attack_L3 = { damage = 44, reaction = "small" },
	attack_L4 = { damage = 56, reaction = "big" },
	attack_L5 = { damage = 90, reaction = "launch" },
	attack_R1 = { damage = 70, reaction = "big" },
	attack_R2 = { damage = 80, reaction = "big" },
	attack_R3 = { damage = 110, reaction = "launch" },
	attack_super = { damage = 240, reaction = "launch", radius = 20 },
	power_emote_1 = { damage = 180, reaction = "launch", radius = 18 },
}
Config.Reach = 9.5 -- studs from the attacker's root, plus the target's radius
Config.TargetRadius = 2
Config.Arc = 150 -- degrees in front of the attacker
Config.PowerPerHit = 8
Config.SuperCost = 100
Config.FadeAttack = 0.1
Config.FadeRecoil = 0.05
Config.HeroStunImmunity = 1.0 -- seconds after a hero recoil during which hits only deal damage
Config.RecoilCancel = 0.25 -- a hero can attack out of a small/big recoil after this many seconds

Config.Enemy = {
	name = "Rival Luchador",
	health = 260,
	damageScale = 0.32,
	walkSpeed = 15,
	attackRange = 8.5,
	attacks = { "attack_L1", "attack_L2", "attack_R1" },
	cooldown = { 2.0, 3.6 },
	maxAttackers = 2, -- enemies swinging at the same time
	waitAfterHeroHit = 0.7, -- don't pile onto a hero that was just hit
	thinkRate = 0.12,
	despawnAfter = 3.5,
}

-- costume recolors for enemies (client EditableImage hue shift of the crimson costume; skin untouched)
Config.Variants = {
	{ name = "Azul", hue = 0.60, sat = 1.0, val = 1.0, gold = "silver" },
	{ name = "Verde", hue = 0.36, sat = 0.9, val = 0.95, gold = "gold" },
	{ name = "Morado", hue = 0.78, sat = 0.9, val = 1.0, gold = "gold" },
	{ name = "Negro", hue = 0.0, sat = 0.0, val = 0.42, gold = "silver" },
}

Config.Waves = { 2, 3, 4, 5, 6 }
Config.WaveBreak = 3
Config.RespawnTime = 4

Config.Emotes = { "emote_taunt", "emote_cheer", "emote_laugh", "emote_dance" }

-- camera: fixed angle like the original brawler camera, facing the arena's back wall (-Z)
Config.Camera = { offset = Vector3.new(0, 21, 27), lookHeight = 3.5, fov = 55, zoomMin = 0.6, zoomMax = 1.6 }

return Config
