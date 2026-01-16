#load "SharedPaths.csx"

using System;
using System.IO;
using System.Threading.Tasks;
using System.Linq;
using System.Collections.Generic;
using System.Text;
using UndertaleModLib.Util;

EnsureDataLoaded();


string CorrectCodeEntryName(string filename)
{
    string corrected = filename;
    corrected = corrected.Replace("_object_", "_Object_");
    corrected = corrected.Replace("_create_", "_Create_");
    corrected = corrected.Replace("_destroy_", "_Destroy_");
    corrected = corrected.Replace("_step_", "_Step_");
    corrected = corrected.Replace("_draw_", "_Draw_");
    corrected = corrected.Replace("_alarm_", "_Alarm_");
    corrected = corrected.Replace("_collision_", "_Collision_");
    corrected = corrected.Replace("_other_", "_Other_");
    return corrected;
}

var ctx = PrepareImportContext();
string objectsRoot = ctx.InputRoot;
string importFolder = Path.Combine(objectsRoot, "CodeEntries");

if (importFolder == null || !Directory.Exists(importFolder))
{
    Console.WriteLine("[ImportGML] No CodeEntries directory found, skipping.");
    return;
}

string[] dirFiles = Directory.GetFiles(importFolder, "*.gml");
if (dirFiles.Length == 0)
{
    Console.WriteLine("[ImportGML] No GML files found in CodeEntries, skipping.");
    return;
}

Console.WriteLine($"[ImportGML] Found {dirFiles.Length} GML file(s) to import");

SetProgressBar(null, "Importing GML", 0, dirFiles.Length);
StartProgressBarUpdater();

SyncBinding("Strings, Code, CodeLocals, Scripts, GlobalInitScripts, GameObjects, Functions, Variables", true);

await Task.Run(() =>
{
    UndertaleModLib.Compiler.CodeImportGroup importGroup = new(Data);
    
    foreach (string file in dirFiles)
    {
        IncrementProgress();

        string code = File.ReadAllText(file);
        string originalCodeName = Path.GetFileNameWithoutExtension(file);
        string correctedCodeName = CorrectCodeEntryName(originalCodeName);
        
        
        var exactMatch = Data.Code.ByName(correctedCodeName);
        if (exactMatch == null)
            exactMatch = Data.Code.ByName(originalCodeName);
        if (exactMatch == null)
            exactMatch = Data.Code.FirstOrDefault(c => 
                c?.Name?.Content != null && 
                c.Name.Content.Equals(correctedCodeName, StringComparison.OrdinalIgnoreCase));
        
        string targetName = exactMatch?.Name?.Content ?? correctedCodeName;
        
        try
        {
            importGroup.QueueReplace(targetName, code);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"[ImportGML] ERROR: QueueReplace failed for '{targetName}': {ex.Message}");
            throw;
        }
    }
    
    SetProgressBar(null, "Compiling code...", dirFiles.Length, dirFiles.Length);
    importGroup.Import();
});

DisableAllSyncBindings();
await StopProgressBarUpdater();
HideProgressBar();

Console.WriteLine($"[ImportGML] Successfully imported {dirFiles.Length} code entries.");