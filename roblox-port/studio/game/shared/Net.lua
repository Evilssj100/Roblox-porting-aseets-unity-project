-- Remote events shared by server and clients (created by the server under ReplicatedStorage.SPSO.Remotes)
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")

local Net = {}
local folder

local function getFolder()
	if folder then return folder end
	local spso = ReplicatedStorage:WaitForChild("SPSO")
	if RunService:IsServer() then
		folder = spso:FindFirstChild("Remotes")
		if not folder then
			folder = Instance.new("Folder")
			folder.Name = "Remotes"
			folder.Parent = spso
		end
	else
		folder = spso:WaitForChild("Remotes")
	end
	return folder
end

function Net.event(name: string): RemoteEvent
	local f = getFolder()
	local e = f:FindFirstChild(name)
	if not e then
		if RunService:IsServer() then
			e = Instance.new("RemoteEvent")
			e.Name = name
			e.Parent = f
		else
			e = f:WaitForChild(name)
		end
	end
	return e
end

function Net.func(name: string): RemoteFunction
	local f = getFolder()
	local e = f:FindFirstChild(name)
	if not e then
		if RunService:IsServer() then
			e = Instance.new("RemoteFunction")
			e.Name = name
			e.Parent = f
		else
			e = f:WaitForChild(name)
		end
	end
	return e
end

return Net
