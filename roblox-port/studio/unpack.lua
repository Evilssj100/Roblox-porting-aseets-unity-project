-- SPSO package unpacker (Studio, Edit mode). Inserts the SPSO_Package model asset (built by
-- tools/build_rbxmx_package.py, uploaded from Blender) and moves every item to its destination,
-- replacing same-named items there. Returns a short report.
--   require(game.ServerStorage.SPSO.Tools.Unpack)(assetId)
return function(source: any): string
	local model = source
	if type(source) == "number" then
		model = game:GetService("InsertService"):LoadAsset(source)
	end
	local pkg = model:FindFirstChild("SPSO_Package", true)
	assert(pkg, "no SPSO_Package in the asset")
	local version = pkg:FindFirstChild("_version")
	local moved = 0
	for _, dest in pkg:GetChildren() do
		if dest:IsA("Folder") then
			local parts = string.split(dest.Name, "/")
			local target: Instance = game:GetService(parts[1])
			for i = 2, #parts do
				local c = target:FindFirstChild(parts[i])
				if not c then
					c = Instance.new("Folder")
					c.Name = parts[i]
					c.Parent = target
				end
				target = c
			end
			for _, it in dest:GetChildren() do
				local meta = it:FindFirstChild("_meta")
				if meta and meta:IsA("StringValue") then
					local m = game:GetService("HttpService"):JSONDecode(meta.Value)
					it:SetAttribute("Chunks", m.chunks)
					it:SetAttribute("Bytes", m.bytes)
					it:SetAttribute("Sha", m.sha)
					meta:Destroy()
				end
				local old = target:FindFirstChild(it.Name)
				if old and old ~= it then old:Destroy() end
				it.Parent = target
				moved += 1
			end
		end
	end
	if model ~= source or type(source) == "number" then model:Destroy() end
	return string.format("unpacked %d items (version %s)", moved, version and version.Value or "?")
end
