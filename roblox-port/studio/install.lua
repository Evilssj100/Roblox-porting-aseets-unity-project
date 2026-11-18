-- SPSO one-call installer for Roblox Studio. Run it through the Studio MCP (execute_luau, Edit) or the
-- command bar, with BASE pointing at a commit of the roblox-port branch:
--   local B = "https://raw.githubusercontent.com/Evilssj100/roblox-porting-aseets-unity-project/<commit>/roblox-port/"
--   return loadstring(game:GetService("HttpService"):GetAsync(B .. "studio/install.lua", true))()(B)
-- It reads studio/manifest.json (written by tools/build_studio_manifest.py) and:
--   * creates/updates every script listed (ModuleScript / Script / LocalScript) at its place in the tree
--   * stores each hero pack as base64 chunks under ReplicatedStorage.SPSO.Heroes.<Hero>.Pack (skipped when
--     the pack's sha256 is unchanged)
--   * runs the setup steps listed (Luau files returning function(BASE, manifest) -> string)
-- opts: { only = "scripts" | "heroes" | "setup" }
return function(BASE: string, opts)
	opts = opts or {}
	local Http = game:GetService("HttpService")
	local function get(path: string): string
		return Http:GetAsync(BASE .. path, true)
	end
	local manifest = Http:JSONDecode(get("studio/manifest.json"))
	local log = {}

	local function resolve(path: string): Instance
		local parts = string.split(path, "/")
		local inst: Instance = game:GetService(parts[1])
		for i = 2, #parts do
			local c = inst:FindFirstChild(parts[i])
			if not c then
				c = Instance.new("Folder")
				c.Name = parts[i]
				c.Parent = inst
			end
			inst = c
		end
		return inst
	end

	if opts.only == nil or opts.only == "scripts" then
		local n = 0
		for _, f in manifest.scripts or {} do
			local parent = resolve(f.parent)
			local inst = parent:FindFirstChild(f.name)
			if inst and inst.ClassName ~= f.class then
				inst:Destroy()
				inst = nil
			end
			if not inst then
				inst = Instance.new(f.class)
				inst.Name = f.name
			end
			local src = f.path and get(f.path) or f.source or ""
			if inst:GetAttribute("Sha") ~= f.sha then
				(inst :: any).Source = src
				inst:SetAttribute("Sha", f.sha)
				n += 1
			end
			inst.Parent = parent
		end
		table.insert(log, string.format("scripts: %d updated of %d", n, #(manifest.scripts or {})))
	end

	if opts.only == nil or opts.only == "heroes" then
		for _, h in manifest.heroes or {} do
			local folder = resolve("ReplicatedStorage/SPSO/Heroes/" .. h.name)
			local pack = folder:FindFirstChild("Pack")
			if pack and pack:GetAttribute("Sha") == h.sha then
				table.insert(log, h.name .. ": pack unchanged")
			else
				local b64 = get(h.path)
				local newPack = Instance.new("Folder")
				newPack.Name = "Pack"
				local CH, n = 190000, 0
				for i = 1, #b64, CH do
					n += 1
					local sv = Instance.new("StringValue")
					sv.Name = string.format("%03d", n)
					sv.Value = string.sub(b64, i, i + CH - 1)
					assert(#sv.Value == math.min(CH, #b64 - i + 1), "StringValue rejected a chunk")
					sv.Parent = newPack
				end
				newPack:SetAttribute("Chunks", n)
				newPack:SetAttribute("Bytes", #b64)
				newPack:SetAttribute("Sha", h.sha)
				if pack then pack:Destroy() end
				newPack.Parent = folder
				table.insert(log, string.format("%s: pack installed (%d chunks, %d bytes)", h.name, n, #b64))
			end
		end
	end

	if opts.only == nil or opts.only == "setup" then
		for _, s in manifest.setup or {} do
			local fn = loadstring(get(s))
			local ok, res = pcall(fn(), BASE, manifest)
			table.insert(log, s .. ": " .. (ok and tostring(res) or ("FAILED " .. tostring(res))))
		end
	end
	return table.concat(log, "\n")
end
