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
string timelinesIn = Path.Combine(inputRoot, "Timelines");

if (!Directory.Exists(timelinesIn))
{
    PrintLine("[ImportTimelines] No Timelines directory found, skipping import.");
    return;
}

string[] timelineFiles = Directory.GetFiles(timelinesIn, "*.json");
if (timelineFiles.Length == 0)
{
    PrintLine("[ImportTimelines] No timeline JSON files found, skipping import.");
    return;
}

PrintLine($"[ImportTimelines] Found {timelineFiles.Length} timeline file(s) to import.");

SetProgressBar(null, "Importing Timelines", 0, timelineFiles.Length);
StartProgressBarUpdater();

SyncBinding("Timelines, Code, Strings", true);

foreach (string timelineFile in timelineFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(timelineFile, Encoding.UTF8);
        string timelineName = Path.GetFileNameWithoutExtension(timelineFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        UndertaleTimeline timeline = Data.Timelines?.ByName(timelineName);
        if (timeline == null)
        {
            PrintLine($"[ImportTimelines] Timeline '{timelineName}' not found in game, skipping (cannot create new timelines)");
            jsonDoc.Dispose();
            IncrementProgress();
            continue;
        }

        if (root.TryGetProperty("moments", out JsonElement momentsElm) && momentsElm.ValueKind == JsonValueKind.Array)
        {
            
            int momentIndex = 0;
            foreach (JsonElement momentElm in momentsElm.EnumerateArray())
            {
                if (momentIndex < timeline.Moments.Count)
                {
                    var moment = timeline.Moments[momentIndex];
                    
                    
                    if (momentElm.TryGetProperty("step", out JsonElement stepElm))
                    {
                        moment.Step = (uint)stepElm.GetInt32();
                    }
                    
                    
                    if (momentElm.TryGetProperty("actions", out JsonElement actionsElm) && actionsElm.ValueKind == JsonValueKind.Array)
                    {
                        if (moment.Event != null)
                        {
                            int actionIndex = 0;
                            foreach (JsonElement actionElm in actionsElm.EnumerateArray())
                            {
                                if (actionIndex < moment.Event.Count)
                                {
                                    var action = moment.Event[actionIndex];
                                    
                                    if (actionElm.TryGetProperty("codeId", out JsonElement codeIdElm))
                                    {
                                        if (codeIdElm.ValueKind == JsonValueKind.String)
                                        {
                                            string codeName = codeIdElm.GetString() ?? "";
                                            if (!string.IsNullOrEmpty(codeName))
                                            {
                                                UndertaleCode code = Data.Code.ByName(codeName);
                                                if (code != null)
                                                {
                                                    action.CodeId = code;
                                                }
                                                else
                                                {
                                                    PrintLine($"[ImportTimelines] Warning: Code '{codeName}' not found for action {actionIndex} in moment {momentIndex} of timeline '{timelineName}'");
                                                }
                                            }
                                        }
                                        else if (codeIdElm.ValueKind == JsonValueKind.Null)
                                        {
                                            action.CodeId = null;
                                        }
                                    }
                                }
                                actionIndex++;
                            }
                        }
                    }
                }
                momentIndex++;
            }
        }

        PrintLine($"[ImportTimelines] Updated timeline: {timelineName}");
        jsonDoc.Dispose();
        IncrementProgress();
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportTimelines] Error importing timeline {Path.GetFileName(timelineFile)}: {ex.Message}");
        IncrementProgress();
    }
}

await StopProgressBarUpdater();
HideProgressBar();
PrintLine("[ImportTimelines] Done.");

