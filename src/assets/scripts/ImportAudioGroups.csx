#load "SharedPaths.csx"

using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;

EnsureDataLoaded();

void PrintLine(string s) => Console.WriteLine(s);

var ctx = PrepareImportContext();
string inputRoot = ctx.InputRoot;
string audioGroupsIn = Path.Combine(inputRoot, "AudioGroups");

if (!Directory.Exists(audioGroupsIn))
{
    PrintLine("[ImportAudioGroups] No AudioGroups directory found, skipping import.");
    return;
}

string[] audioGroupFiles = Directory.GetFiles(audioGroupsIn, "*.json");
if (audioGroupFiles.Length == 0)
{
    PrintLine("[ImportAudioGroups] No audio group JSON files found, skipping import.");
    return;
}

PrintLine($"[ImportAudioGroups] Found {audioGroupFiles.Length} audio group file(s) to import.");

SetProgressBar(null, "Importing Audio Groups", 0, audioGroupFiles.Length);
StartProgressBarUpdater();

SyncBinding("AudioGroups, Strings", true);

foreach (string audioGroupFile in audioGroupFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(audioGroupFile, Encoding.UTF8);
        string audioGroupName = Path.GetFileNameWithoutExtension(audioGroupFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        UndertaleAudioGroup audioGroup = Data.AudioGroups?.ByName(audioGroupName);
        if (audioGroup == null)
        {
            PrintLine($"[ImportAudioGroups] Audio group '{audioGroupName}' not found in game, skipping (cannot create new audio groups)");
            jsonDoc.Dispose();
            IncrementProgress();
            continue;
        }

        if (root.TryGetProperty("path", out JsonElement pathElm))
        {
            string path = pathElm.GetString() ?? "";
            if (!string.IsNullOrEmpty(path))
            {
                audioGroup.Path = Data.Strings.MakeString(path);
            }
        }

        PrintLine($"[ImportAudioGroups] Updated audio group: {audioGroupName}");
        jsonDoc.Dispose();
        IncrementProgress();
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportAudioGroups] Error importing audio group {Path.GetFileName(audioGroupFile)}: {ex.Message}");
        IncrementProgress();
    }
}

await StopProgressBarUpdater();
HideProgressBar();
PrintLine("[ImportAudioGroups] Done.");

