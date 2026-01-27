


using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
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

string audioGroupsIn = GetInputDirectory();
PrintLine($"[ImportAudioGroups] Importing from: {audioGroupsIn}");

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

int created = 0;
int updated = 0;

foreach (string audioGroupFile in audioGroupFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(audioGroupFile, Encoding.UTF8);
        string audioGroupName = Path.GetFileNameWithoutExtension(audioGroupFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        UndertaleAudioGroup audioGroup = Data.AudioGroups?.ByName(audioGroupName);
        bool isNew = false;
        
        if (audioGroup == null)
        {
            
            audioGroup = new UndertaleAudioGroup();
            audioGroup.Name = Data.Strings.MakeString(audioGroupName);
            isNew = true;
            PrintLine($"[ImportAudioGroups] Creating NEW audio group: {audioGroupName}");
        }

        if (root.TryGetProperty("path", out JsonElement pathElm))
        {
            string path = pathElm.GetString() ?? "";
            if (!string.IsNullOrEmpty(path))
            {
                audioGroup.Path = Data.Strings.MakeString(path);
            }
        }

        if (isNew)
        {
            Data.AudioGroups.Add(audioGroup);
            created++;
            PrintLine($"[ImportAudioGroups] Created new audio group: {audioGroupName}");
        }
        else
        {
            updated++;
            PrintLine($"[ImportAudioGroups] Updated audio group: {audioGroupName}");
        }
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
PrintLine($"[ImportAudioGroups] Done. Created: {created}, Updated: {updated}");


