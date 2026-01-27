

using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using UndertaleModLib;
using UndertaleModLib.Models;


void PrintLine(string s) => Console.WriteLine(s);

string GetOutputDirectory()
{
    string outputDir = Environment.GetEnvironmentVariable("OUTPUT_DIR");
    if (string.IsNullOrEmpty(outputDir))
        throw new ScriptException("OUTPUT_DIR environment variable is not set.");
    if (!Directory.Exists(outputDir))
        Directory.CreateDirectory(outputDir);
    return outputDir;
}


EnsureDataLoaded();

if (Data.GeneralInfo == null)
{
    ScriptError("GeneralInfo is null. Cannot export.");
    return;
}

string outputPath = GetOutputDirectory();
string jsonPath = Path.Combine(outputPath, "GeneralInfo.json");
PrintLine($"[ExportGeneralInfo] Exporting to: {jsonPath}");

try
{
    using (var stream = new FileStream(jsonPath, FileMode.Create))
    using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
    {
        writer.WriteStartObject();

        
        writer.WriteBoolean("isDebuggerDisabled", Data.GeneralInfo.IsDebuggerDisabled);
        writer.WriteNumber("bytecodeVersion", Data.GeneralInfo.BytecodeVersion);
        writer.WriteNumber("padding", Data.GeneralInfo.Padding);

        
        writer.WriteString("fileName", Data.GeneralInfo.FileName?.Content ?? "");
        writer.WriteString("config", Data.GeneralInfo.Config?.Content ?? "");
        
        
        writer.WriteNumber("lastObj", Data.GeneralInfo.LastObj);
        writer.WriteNumber("lastTile", Data.GeneralInfo.LastTile);

        
        writer.WriteNumber("gameID", Data.GeneralInfo.GameID);

        
        writer.WriteString("directPlayGuid", Data.GeneralInfo.DirectPlayGuid.ToString());

        
        writer.WriteString("name", Data.GeneralInfo.Name?.Content ?? "");

        
        writer.WriteNumber("major", Data.GeneralInfo.Major);
        writer.WriteNumber("minor", Data.GeneralInfo.Minor);
        writer.WriteNumber("release", Data.GeneralInfo.Release);
        writer.WriteNumber("build", Data.GeneralInfo.Build);

        
        writer.WriteNumber("defaultWindowWidth", Data.GeneralInfo.DefaultWindowWidth);
        writer.WriteNumber("defaultWindowHeight", Data.GeneralInfo.DefaultWindowHeight);

        
        writer.WriteNumber("infoFlags", (uint)Data.GeneralInfo.Info);

        
        writer.WritePropertyName("infoFlagsDecoded");
        writer.WriteStartObject();
        writer.WriteBoolean("fullscreen", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.Fullscreen) != 0);
        writer.WriteBoolean("syncVertex1", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.SyncVertex1) != 0);
        writer.WriteBoolean("syncVertex2", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.SyncVertex2) != 0);
        writer.WriteBoolean("interpolate", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.Interpolate) != 0);
        writer.WriteBoolean("scale", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.Scale) != 0);
        writer.WriteBoolean("showCursor", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.ShowCursor) != 0);
        writer.WriteBoolean("sizeable", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.Sizeable) != 0);
        writer.WriteBoolean("screenKey", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.ScreenKey) != 0);
        writer.WriteBoolean("syncVertex3", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.SyncVertex3) != 0);
        writer.WriteBoolean("studioVersionB1", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.StudioVersionB1) != 0);
        writer.WriteBoolean("studioVersionB2", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.StudioVersionB2) != 0);
        writer.WriteBoolean("studioVersionB3", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.StudioVersionB3) != 0);
        writer.WriteBoolean("studioVersionMask", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.StudioVersionMask) != 0);
        writer.WriteBoolean("steamEnabled", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.SteamEnabled) != 0);
        writer.WriteBoolean("useAppDataSaveLocation", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.UseAppDataSaveLocation) != 0);
        writer.WriteBoolean("borderlessWindow", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.BorderlessWindow) != 0);
        writer.WriteBoolean("javaScriptMode", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.JavaScriptMode) != 0);
        writer.WriteBoolean("licenseExclusions", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.LicenseExclusions) != 0);
        writer.WriteBoolean("gameRunFromGMS2IDE", (Data.GeneralInfo.Info & UndertaleGeneralInfo.InfoFlags.GameRunFromGMS2IDE) != 0);
        writer.WriteEndObject();

        
        writer.WriteNumber("licenseCRC32", Data.GeneralInfo.LicenseCRC32);
        
        writer.WritePropertyName("licenseMD5");
        writer.WriteStartArray();
        if (Data.GeneralInfo.LicenseMD5 != null)
        {
            foreach (byte b in Data.GeneralInfo.LicenseMD5)
                writer.WriteNumberValue(b);
        }
        writer.WriteEndArray();

        
        writer.WriteNumber("timestamp", Data.GeneralInfo.Timestamp);

        
        writer.WriteString("displayName", Data.GeneralInfo.DisplayName?.Content ?? "");

        
        writer.WriteNumber("activeTargets", Data.GeneralInfo.ActiveTargets);

        
        writer.WriteNumber("functionClassifications", (ulong)Data.GeneralInfo.FunctionClassifications);

        
        writer.WriteNumber("steamAppID", Data.GeneralInfo.SteamAppID);

        
        if (Data.GeneralInfo.BytecodeVersion >= 14)
        {
            writer.WriteNumber("debuggerPort", Data.GeneralInfo.DebuggerPort);
        }

        
        writer.WritePropertyName("roomOrder");
        writer.WriteStartArray();
        foreach (var roomRef in Data.GeneralInfo.RoomOrder)
        {
            if (roomRef?.Resource?.Name?.Content != null)
                writer.WriteStringValue(roomRef.Resource.Name.Content);
            else
                writer.WriteNullValue();
        }
        writer.WriteEndArray();

        
        if (Data.GeneralInfo.Major >= 2)
        {
            
            writer.WritePropertyName("gms2RandomUID");
            writer.WriteStartArray();
            if (Data.GeneralInfo.GMS2RandomUID != null)
            {
                foreach (long uid in Data.GeneralInfo.GMS2RandomUID)
                    writer.WriteNumberValue(uid);
            }
            writer.WriteEndArray();

            
            writer.WriteNumber("gms2FPS", Data.GeneralInfo.GMS2FPS);

            
            writer.WriteBoolean("gms2AllowStatistics", Data.GeneralInfo.GMS2AllowStatistics);

            
            writer.WritePropertyName("gms2GameGUID");
            writer.WriteStartArray();
            if (Data.GeneralInfo.GMS2GameGUID != null)
            {
                foreach (byte b in Data.GeneralInfo.GMS2GameGUID)
                    writer.WriteNumberValue(b);
            }
            writer.WriteEndArray();
        }

        writer.WriteEndObject();
    }

    PrintLine($"[ExportGeneralInfo] Export complete: {jsonPath}");
}
catch (Exception ex)
{
    PrintLine($"[ExportGeneralInfo] Export failed: {ex.Message}");
    ScriptError($"Failed to export GeneralInfo: {ex.Message}");
}
