// Script by Jockeholm based off of a script by Kneesnap.
// Major help and edited by Samuel Roy

using System;
using System.IO;
using System.Threading.Tasks;
using System.Linq;
using UndertaleModLib.Util;
using System.Reflection;

EnsureDataLoaded();

string CorrectCodeEntryName(string filename)
{
    string corrected = filename;
    
    // Fix common event name casing issues
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

// Check code directory.
string chapterNo = File.ReadAllText(@Convert.ToString(Directory.GetParent(Convert.ToString(Directory.GetParent(Convert.ToString(Assembly.GetEntryAssembly().Location)))) + "/output/Cache/running/chapterNumber.txt"));
string importFolder = @Convert.ToString(Directory.GetParent(Convert.ToString(Directory.GetParent(Convert.ToString(Assembly.GetEntryAssembly().Location)))) + "/output/xDeltaCombiner/"+chapterNo+"/1/Objects/CodeEntries");
if (importFolder == null)
    throw new ScriptException("The import folder was not set.");

string[] dirFiles = Directory.GetFiles(@importFolder);
if (dirFiles.Length != 0){

// Ask whether they want to link code. If no, will only generate code entry.
// If yes, will try to add code to objects and scripts depending upon its name
bool doParse = true;

SetProgressBar(null, "Files", 0, dirFiles.Length);
StartProgressBarUpdater();


SyncBinding("Strings, Code, CodeLocals, Scripts, GlobalInitScripts, GameObjects, Functions, Variables", true);
await Task.Run(() =>
{
    UndertaleModLib.Compiler.CodeImportGroup importGroup = new(Data);
    
    // First, let's see what code entries actually exist
    Console.WriteLine("=== EXISTING CODE ENTRIES ===");
    var existingEntries = Data.Code.Where(c => c?.Name?.Content != null).ToList();
    foreach (var entry in existingEntries.Take(10)) // Show first 10
    {
        Console.WriteLine($"  EXISTS: {entry.Name.Content}");
    }
    Console.WriteLine($"Total existing entries: {existingEntries.Count}");
    
    Console.WriteLine("\n=== PROCESSING FILES ===");
    
    foreach (string file in dirFiles)
    {
        IncrementProgress();

        string code = File.ReadAllText(file);
        string originalCodeName = Path.GetFileNameWithoutExtension(file);
        string correctedCodeName = CorrectCodeEntryName(originalCodeName);
        
        Console.WriteLine($"\nFILE: {Path.GetFileName(file)}");
        Console.WriteLine($"  Original name: {originalCodeName}");
        Console.WriteLine($"  Corrected name: {correctedCodeName}");
        Console.WriteLine($"  Code length: {code.Length}");
        Console.WriteLine($"  Code preview: {code.Substring(0, Math.Min(50, code.Length))}...");
        
        // Check if entry exists with exact name
        var exactMatch = Data.Code.ByName(correctedCodeName);
        Console.WriteLine($"  Exact match found: {exactMatch != null}");
        
        if (exactMatch == null)
        {
            // Try original name
            exactMatch = Data.Code.ByName(originalCodeName);
            Console.WriteLine($"  Original name match: {exactMatch != null}");
        }
        
        if (exactMatch == null)
        {
            // Try case-insensitive search
            exactMatch = Data.Code.FirstOrDefault(c => 
                c?.Name?.Content != null && 
                c.Name.Content.Equals(correctedCodeName, StringComparison.OrdinalIgnoreCase));
            Console.WriteLine($"  Case-insensitive match: {exactMatch != null}");
        }
        
        // Use the name that actually exists
        string targetName = exactMatch?.Name?.Content ?? correctedCodeName;
        Console.WriteLine($"  Target name: {targetName}");
        Console.WriteLine($"  Will create new entry: {exactMatch == null}");
        
        try
        {
            importGroup.QueueReplace(targetName, code);
            Console.WriteLine($"  ✓ Queued successfully");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  ✗ Queue failed: {ex.Message}");
        }
    }
    
    Console.WriteLine("\n=== PERFORMING IMPORT ===");
    SetProgressBar(null, "Performing final import...", dirFiles.Length, dirFiles.Length);
    importGroup.Import();
    Console.WriteLine("Import completed");
});
DisableAllSyncBindings();

await StopProgressBarUpdater();
HideProgressBar();
ScriptMessage("All files successfully imported.");
}