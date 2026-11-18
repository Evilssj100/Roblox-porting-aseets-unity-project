--!native
-- SPSO HeroPack: decodes an SPSOHRO1 hero pack (format: roblox-port/tools/spso_hero_pack.py).
-- The pack is stored in the place as base64 chunks (StringValues named 001, 002, ...) under
-- ReplicatedStorage.SPSO.Heroes.<Hero>.Pack, so it works in live servers without HTTP.
-- Curve data stays in the decompressed buffer; only key times and per-key offsets become Luau tables.
local EncodingService = game:GetService("EncodingService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local HeroPack = {}
local cache = {}
local DIM = { [0] = 4, [1] = 3, [2] = 3 }
local f32tmp = buffer.create(4)

local function toF32(x: number): number
	buffer.writef32(f32tmp, 0, x)
	return buffer.readf32(f32tmp, 0)
end

function HeroPack.decode(raw: buffer)
	assert(buffer.readstring(raw, 0, 8) == "SPSOHRO1", "not an SPSO hero pack")
	local o = 8
	local function u8() local v = buffer.readu8(raw, o); o += 1; return v end
	local function u16() local v = buffer.readu16(raw, o); o += 2; return v end
	local function i16() local v = buffer.readi16(raw, o); o += 2; return v end
	local function u32() local v = buffer.readu32(raw, o); o += 4; return v end
	local function i32() local v = buffer.readi32(raw, o); o += 4; return v end
	local function f32() local v = buffer.readf32(raw, o); o += 4; return v end
	local function f64() local v = buffer.readf64(raw, o); o += 8; return v end
	local function str() local n = u16(); local s = buffer.readstring(raw, o, n); o += n; return s end
	local function f32s(n) local t = table.create(n); for i = 1, n do t[i] = buffer.readf32(raw, o); o += 4 end; return t end

	local pack = { buf = raw, version = u32(), studs = f32(), hero = str(),
		nodes = {}, nodeIndex = {}, bones = {}, boneIndex = {}, parts = {}, clips = {}, clipList = {}, tests = {}, sigs = {} }
	for i = 1, u16() do
		local n = { name = str(), parent = i16() + 1, t = f32s(3), q = f32s(4), s = f32s(3) }
		pack.nodes[i] = n
		pack.nodeIndex[n.name] = i
	end
	for b = 1, u16() do
		local bone = { node = u16() + 1, binv = f32s(12), radius = f32() }
		bone.name = pack.nodes[bone.node].name
		pack.bones[b] = bone
		pack.boneIndex[bone.name] = b
	end
	for p = 1, u16() do
		local part = { name = str() }
		local nV = u32()
		part.nV = nV
		part.pos = f32s(nV * 3)
		local bi = table.create(nV * 4)
		for k = 1, nV * 4 do bi[k] = buffer.readu8(raw, o) + 1; o += 1 end
		part.bi = bi
		part.bw = f32s(nV * 4)
		local nN = u32()
		part.nN = nN
		part.nvert = table.create(nN)
		part.nrm = table.create(nN * 3)
		for k = 1, nN do
			part.nvert[k] = u32() + 1
			part.nrm[3 * k - 2], part.nrm[3 * k - 1], part.nrm[3 * k] = f32(), f32(), f32()
		end
		part.nUV = u32()
		part.uv = f32s(part.nUV * 2)
		local nT = u32()
		part.nT = nT
		local tri = table.create(nT * 9)
		for k = 1, nT * 9 do tri[k] = buffer.readu32(raw, o) + 1; o += 4 end
		part.tri = tri
		pack.parts[p] = part
	end
	for c = 1, u16() do
		local clip = { index = c, name = str(), duration = f32(), rate = f32(), wrap = u8(), events = {}, curves = {} }
		clip.rootMotion = u8() % 2 == 1
		for e = 1, u16() do
			clip.events[e] = { time = f32(), fn = str(), data = str(), float = f32(), int = i32() }
		end
		table.sort(clip.events, function(a, b) return a.time < b.time end)
		for k = 1, u16() do
			local cv = { node = u16() + 1, kind = u8() }
			local flags = u8()
			local dim = DIM[cv.kind]
			cv.dim = dim
			if flags % 2 == 1 then
				cv.const = f32s(dim)
			else
				local n = u16()
				cv.n = n
				local times = table.create(n)
				if math.floor(flags / 2) % 2 == 1 then
					for i = 1, n do times[i] = toF32(buffer.readu16(raw, o) / clip.rate); o += 2 end
				else
					for i = 1, n do times[i] = buffer.readf32(raw, o); o += 4 end
				end
				cv.times = times
				cv.vOff = o
				o += n * dim * 4
				cv.inOff = o
				o += n * dim * 4
				local outOffs = table.create(n)
				if math.floor(flags / 4) % 2 == 1 then
					local maskOff = o
					o += (n + 7) // 8
					for i = 1, n do
						local byte = buffer.readu8(raw, maskOff + (i - 1) // 8)
						if bit32.btest(byte, bit32.lshift(1, (i - 1) % 8)) then
							outOffs[i] = o
							o += dim * 4
						else
							outOffs[i] = cv.inOff + (i - 1) * dim * 4
						end
					end
				else
					for i = 1, n do outOffs[i] = cv.inOff + (i - 1) * dim * 4 end
				end
				cv.outOffs = outOffs
			end
			clip.curves[k] = cv
		end
		pack.clips[clip.name] = clip
		pack.clipList[c] = clip
	end
	local NB = #pack.bones
	for i = 1, u16() do
		pack.tests[i] = { clip = u16() + 1, time = f32(), S = f32s(NB * 12) }
	end
	for i = 1, u16() do
		pack.sigs[i] = { clip = u16() + 1, time = f32(), sig = f64() }
	end
	assert(o == buffer.len(raw), "pack has trailing bytes")
	return pack
end

-- folder: Folder of StringValues (base64 of the zstd-compressed pack), named in order
function HeroPack.fromFolder(folder: Instance)
	local chunks = {}
	for _, c in folder:GetChildren() do
		if c:IsA("StringValue") then table.insert(chunks, c) end
	end
	table.sort(chunks, function(a, b) return a.Name < b.Name end)
	local parts = table.create(#chunks)
	for i, c in chunks do parts[i] = c.Value end
	local z = EncodingService:Base64Decode(buffer.fromstring(table.concat(parts)))
	return HeroPack.decode(EncodingService:DecompressBuffer(z, Enum.CompressionAlgorithm.Zstd))
end

-- Cached load of ReplicatedStorage.SPSO.Heroes.<hero>.Pack (waits for replication on clients)
function HeroPack.get(hero: string)
	if cache[hero] then return cache[hero] end
	local root = ReplicatedStorage:WaitForChild("SPSO"):WaitForChild("Heroes"):WaitForChild(hero)
	local folder = root:WaitForChild("Pack")
	local expected = folder:GetAttribute("Chunks")
	while expected and #folder:GetChildren() < expected do task.wait() end
	local pack = HeroPack.fromFolder(folder)
	cache[hero] = pack
	return pack
end

return HeroPack
