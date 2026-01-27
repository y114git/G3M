

using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;


void PrintLine(string s) => Console.WriteLine(s);

string GetInputDirectory()
{
    string inputDir = Environment.GetEnvironmentVariable("INPUT_DIR");
    if (string.IsNullOrEmpty(inputDir))
        throw new ScriptException("INPUT_DIR environment variable is not set.");
    if (!Directory.Exists(inputDir))
        throw new ScriptException($"INPUT_DIR directory does not exist: {inputDir}");
    return inputDir;
}


EnsureDataLoaded();

if (Data.GeneralInfo == null)
{
    ScriptError("GeneralInfo is null. Cannot import.");
    return;
}

string inputPath = GetInputDirectory();
string jsonPath = Path.Combine(inputPath, "GeneralInfo.json");

if (!File.Exists(jsonPath))
{
    ScriptError($"GeneralInfo.json not found at: {jsonPath}");
    return;
}

PrintLine($"[ImportGeneralInfo] Importing from: {jsonPath}");

try
{
    string jsonContent = File.ReadAllText(jsonPath, Encoding.UTF8);
    JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
    JsonElement root = jsonDoc.RootElement;

    
    if (root.TryGetProperty("isDebuggerDisabled", out JsonElement isDebuggerElm))
        Data.GeneralInfo.IsDebuggerDisabled = isDebuggerElm.GetBoolean();

    if (root.TryGetProperty("bytecodeVersion", out JsonElement bytecodeElm))
        Data.GeneralInfo.BytecodeVersion = (byte)bytecodeElm.GetInt32();

    if (root.TryGetProperty("padding", out JsonElement paddingElm))
        Data.GeneralInfo.Padding = (ushort)paddingElm.GetInt32();

    
    if (root.TryGetProperty("fileName", out JsonElement fileNameElm))
    {
        string fileName = fileNameElm.GetString();
        if (!string.IsNullOrEmpty(fileName))
            Data.GeneralInfo.FileName = Data.Strings.MakeString(fileName);
    }

    if (root.TryGetProperty("config", out JsonElement configElm))
    {
        string config = configElm.GetString();
        if (!string.IsNullOrEmpty(config))
            Data.GeneralInfo.Config = Data.Strings.MakeString(config);
    }

    
    if (root.TryGetProperty("lastObj", out JsonElement lastObjElm))
        Data.GeneralInfo.LastObj = (uint)lastObjElm.GetInt64();

    if (root.TryGetProperty("lastTile", out JsonElement lastTileElm))
        Data.GeneralInfo.LastTile = (uint)lastTileElm.GetInt64();

    
    if (root.TryGetProperty("gameID", out JsonElement gameIDElm))
        Data.GeneralInfo.GameID = (uint)gameIDElm.GetInt64();

    
    if (root.TryGetProperty("directPlayGuid", out JsonElement directPlayGuidElm))
    {
        string guidStr = directPlayGuidElm.GetString();
        if (!string.IsNullOrEmpty(guidStr))
        {
            if (Guid.TryParse(guidStr, out Guid guid))
                Data.GeneralInfo.DirectPlayGuid = guid;
        }
    }

    
    if (root.TryGetProperty("name", out JsonElement nameElm))
    {
        string name = nameElm.GetString();
        if (!string.IsNullOrEmpty(name))
            Data.GeneralInfo.Name = Data.Strings.MakeString(name);
    }

    
    if (root.TryGetProperty("major", out JsonElement majorElm))
        Data.GeneralInfo.Major = (uint)majorElm.GetInt64();

    if (root.TryGetProperty("minor", out JsonElement minorElm))
        Data.GeneralInfo.Minor = (uint)minorElm.GetInt64();

    if (root.TryGetProperty("release", out JsonElement releaseElm))
        Data.GeneralInfo.Release = (uint)releaseElm.GetInt64();

    if (root.TryGetProperty("build", out JsonElement buildElm))
        Data.GeneralInfo.Build = (uint)buildElm.GetInt64();

    
    if (root.TryGetProperty("defaultWindowWidth", out JsonElement windowWidthElm))
        Data.GeneralInfo.DefaultWindowWidth = (uint)windowWidthElm.GetInt64();

    if (root.TryGetProperty("defaultWindowHeight", out JsonElement windowHeightElm))
        Data.GeneralInfo.DefaultWindowHeight = (uint)windowHeightElm.GetInt64();

    
    if (root.TryGetProperty("infoFlags", out JsonElement infoFlagsElm))
    {
        Data.GeneralInfo.Info = (UndertaleGeneralInfo.InfoFlags)infoFlagsElm.GetUInt32();
    }

    
    if (root.TryGetProperty("licenseCRC32", out JsonElement licenseCRC32Elm))
        Data.GeneralInfo.LicenseCRC32 = (uint)licenseCRC32Elm.GetInt64();

    if (root.TryGetProperty("licenseMD5", out JsonElement licenseMD5Elm) && licenseMD5Elm.ValueKind == JsonValueKind.Array)
    {
        var md5List = new List<byte>();
        foreach (JsonElement byteElm in licenseMD5Elm.EnumerateArray())
        {
            md5List.Add((byte)byteElm.GetInt32());
        }
        Data.GeneralInfo.LicenseMD5 = md5List.ToArray();
    }

    
    if (root.TryGetProperty("timestamp", out JsonElement timestampElm))
        Data.GeneralInfo.Timestamp = (ulong)timestampElm.GetUInt64();

    
    if (root.TryGetProperty("displayName", out JsonElement displayNameElm))
    {
        string displayName = displayNameElm.GetString();
        if (!string.IsNullOrEmpty(displayName))
            Data.GeneralInfo.DisplayName = Data.Strings.MakeString(displayName);
    }

    
    if (root.TryGetProperty("activeTargets", out JsonElement activeTargetsElm))
        Data.GeneralInfo.ActiveTargets = activeTargetsElm.GetUInt64();

    
    if (root.TryGetProperty("functionClassifications", out JsonElement funcClassElm))
        Data.GeneralInfo.FunctionClassifications = (UndertaleGeneralInfo.FunctionClassification)funcClassElm.GetUInt64();

    
    if (root.TryGetProperty("steamAppID", out JsonElement steamAppIDElm))
        Data.GeneralInfo.SteamAppID = steamAppIDElm.GetInt32();

    
    if (Data.GeneralInfo.BytecodeVersion >= 14)
    {
        if (root.TryGetProperty("debuggerPort", out JsonElement debuggerPortElm))
            Data.GeneralInfo.DebuggerPort = (uint)debuggerPortElm.GetInt64();
    }

    
    if (root.TryGetProperty("roomOrder", out JsonElement roomOrderElm) && roomOrderElm.ValueKind == JsonValueKind.Array)
    {
        Data.GeneralInfo.RoomOrder.Clear();
        
        foreach (JsonElement roomNameElm in roomOrderElm.EnumerateArray())
        {
            if (roomNameElm.ValueKind == JsonValueKind.Null)
            {
                PrintLine("[ImportGeneralInfo] Warning: Null room in room order, skipping");
                continue;
            }

            string roomName = roomNameElm.GetString();
            if (string.IsNullOrEmpty(roomName))
            {
                PrintLine("[ImportGeneralInfo] Warning: Empty room name in room order, skipping");
                continue;
            }

            UndertaleRoom room = Data.Rooms.ByName(roomName);
            if (room != null)
            {
                Data.GeneralInfo.RoomOrder.Add(new UndertaleResourceById<UndertaleRoom, UndertaleChunkROOM>() { Resource = room });
                PrintLine($"[ImportGeneralInfo] Added room to order: {roomName}");
            }
            else
            {
                PrintLine($"[ImportGeneralInfo] Warning: Room not found: {roomName}");
            }
        }
    }

    
    if (Data.GeneralInfo.Major >= 2)
    {
        
        if (root.TryGetProperty("gms2RandomUID", out JsonElement gms2UIDElm) && gms2UIDElm.ValueKind == JsonValueKind.Array)
        {
            Data.GeneralInfo.GMS2RandomUID = new List<long>();
            foreach (JsonElement uidElm in gms2UIDElm.EnumerateArray())
            {
                Data.GeneralInfo.GMS2RandomUID.Add(uidElm.GetInt64());
            }
        }

        
        if (root.TryGetProperty("gms2FPS", out JsonElement gms2FPSElm))
            Data.GeneralInfo.GMS2FPS = (float)gms2FPSElm.GetDouble();

        
        if (root.TryGetProperty("gms2AllowStatistics", out JsonElement gms2AllowStatsElm))
            Data.GeneralInfo.GMS2AllowStatistics = gms2AllowStatsElm.GetBoolean();

        
        if (root.TryGetProperty("gms2GameGUID", out JsonElement gms2GameGUIDElm) && gms2GameGUIDElm.ValueKind == JsonValueKind.Array)
        {
            var guidList = new List<byte>();
            foreach (JsonElement byteElm in gms2GameGUIDElm.EnumerateArray())
            {
                guidList.Add((byte)byteElm.GetInt32());
            }
            Data.GeneralInfo.GMS2GameGUID = guidList.ToArray();
        }
    }

    jsonDoc.Dispose();

    PrintLine($"[ImportGeneralInfo] Import complete");
    PrintLine($"[ImportGeneralInfo] Game: {Data.GeneralInfo.DisplayName?.Content ?? "N/A"}");
    PrintLine($"[ImportGeneralInfo] Version: {Data.GeneralInfo.Major}.{Data.GeneralInfo.Minor}.{Data.GeneralInfo.Release}.{Data.GeneralInfo.Build}");
    PrintLine($"[ImportGeneralInfo] Bytecode: {Data.GeneralInfo.BytecodeVersion}");
    PrintLine($"[ImportGeneralInfo] Room order: {Data.GeneralInfo.RoomOrder.Count} rooms");
}
catch (Exception ex)
{
    PrintLine($"[ImportGeneralInfo] Import failed: {ex.Message}");
    ScriptError($"Failed to import GeneralInfo: {ex.Message}\n{ex.StackTrace}");
}
