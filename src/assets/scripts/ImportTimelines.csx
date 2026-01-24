


using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Collections.ObjectModel;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;




string InputDirectory = "";




void PrintLine(string s) => Console.WriteLine(s);

string ResolveInputDirectory()
{
    if (!string.IsNullOrEmpty(InputDirectory) && Directory.Exists(InputDirectory))
        return InputDirectory;

    if (string.IsNullOrEmpty(FilePath))
        throw new ScriptException("No data.win file loaded. Please load a game data file first.");

    string dataWinDir = Path.GetDirectoryName(FilePath);
    string timelinesDir = Path.Combine(dataWinDir, "Objects", "Timelines");
    
    if (Directory.Exists(timelinesDir))
        return timelinesDir;

    throw new ScriptException($"Timelines directory not found at: {timelinesDir}\nPlease specify InputDirectory or place timelines in an 'Objects/Timelines' folder next to data.win.");
}




EnsureDataLoaded();

string timelinesIn = ResolveInputDirectory();
PrintLine($"[ImportTimelines] Importing from: {timelinesIn}");

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

int timelinesCreated = 0;
int timelinesUpdated = 0;

foreach (string timelineFile in timelineFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(timelineFile, Encoding.UTF8);
        string timelineName = Path.GetFileNameWithoutExtension(timelineFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        if (root.TryGetProperty("name", out JsonElement nameElm))
        {
            timelineName = nameElm.GetString() ?? timelineName;
        }
        
        UndertaleTimeline timeline = Data.Timelines?.ByName(timelineName);
        bool isNew = false;
        
        if (timeline == null)
        {
            timeline = new UndertaleTimeline();
            timeline.Name = Data.Strings.MakeString(timelineName);
            timeline.Moments = new ObservableCollection<UndertaleTimeline.UndertaleTimelineMoment>();
            isNew = true;
            timelinesCreated++;
        }
        else
        {
            timelinesUpdated++;
        }

        if (root.TryGetProperty("moments", out JsonElement momentsElm) && momentsElm.ValueKind == JsonValueKind.Array)
        {
            var momentsArray = momentsElm.EnumerateArray().ToArray();
            
            for (int momentIndex = 0; momentIndex < momentsArray.Length; momentIndex++)
            {
                JsonElement momentElm = momentsArray[momentIndex];
                
                UndertaleTimeline.UndertaleTimelineMoment moment;
                
                if (momentIndex < timeline.Moments.Count)
                {
                    moment = timeline.Moments[momentIndex];
                }
                else
                {
                    moment = new UndertaleTimeline.UndertaleTimelineMoment();
                    moment.Event = new UndertalePointerList<UndertaleGameObject.EventAction>();
                    timeline.Moments.Add(moment);
                }
                
                if (momentElm.TryGetProperty("step", out JsonElement stepElm))
                {
                    moment.Step = (uint)stepElm.GetInt64();
                }
                
                if (momentElm.TryGetProperty("actions", out JsonElement actionsElm) && actionsElm.ValueKind == JsonValueKind.Array)
                {
                    if (moment.Event == null)
                    {
                        moment.Event = new UndertalePointerList<UndertaleGameObject.EventAction>();
                    }
                    
                    var actionsArray = actionsElm.EnumerateArray().ToArray();
                    
                    for (int actionIndex = 0; actionIndex < actionsArray.Length; actionIndex++)
                    {
                        JsonElement actionElm = actionsArray[actionIndex];
                        
                        UndertaleGameObject.EventAction action;
                        
                        if (actionIndex < moment.Event.Count)
                        {
                            action = moment.Event[actionIndex];
                        }
                        else
                        {
                            action = new UndertaleGameObject.EventAction();
                            moment.Event.Add(action);
                        }
                        
                        if (actionElm.TryGetProperty("libId", out JsonElement libIdElm))
                            action.LibID = (uint)libIdElm.GetInt64();
                        if (actionElm.TryGetProperty("id", out JsonElement idElm))
                            action.ID = (uint)idElm.GetInt64();
                        if (actionElm.TryGetProperty("kind", out JsonElement kindElm))
                            action.Kind = (uint)kindElm.GetInt64();
                        if (actionElm.TryGetProperty("useRelative", out JsonElement useRelativeElm))
                            action.UseRelative = useRelativeElm.GetBoolean();
                        if (actionElm.TryGetProperty("isQuestion", out JsonElement isQuestionElm))
                            action.IsQuestion = isQuestionElm.GetBoolean();
                        if (actionElm.TryGetProperty("useApplyTo", out JsonElement useApplyToElm))
                            action.UseApplyTo = useApplyToElm.GetBoolean();
                        if (actionElm.TryGetProperty("exeType", out JsonElement exeTypeElm))
                            action.ExeType = (uint)exeTypeElm.GetInt64();
                        if (actionElm.TryGetProperty("actionName", out JsonElement actionNameElm))
                        {
                            string actionName = actionNameElm.GetString();
                            if (!string.IsNullOrEmpty(actionName))
                                action.ActionName = Data.Strings.MakeString(actionName);
                        }
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
                                }
                            }
                            else if (codeIdElm.ValueKind == JsonValueKind.Null)
                            {
                                action.CodeId = null;
                            }
                        }
                        if (actionElm.TryGetProperty("argumentCount", out JsonElement argumentCountElm))
                            action.ArgumentCount = (uint)argumentCountElm.GetInt64();
                        if (actionElm.TryGetProperty("who", out JsonElement whoElm))
                            action.Who = whoElm.GetInt32();
                        if (actionElm.TryGetProperty("relative", out JsonElement relativeElm))
                            action.Relative = relativeElm.GetBoolean();
                        if (actionElm.TryGetProperty("isNot", out JsonElement isNotElm))
                            action.IsNot = isNotElm.GetBoolean();
                    }
                }
            }
        }

        if (isNew)
        {
            Data.Timelines.Add(timeline);
        }

        PrintLine($"[ImportTimelines] {(isNew ? "Created" : "Updated")} timeline: {timelineName}");
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
PrintLine($"[ImportTimelines] Done. Created: {timelinesCreated}, Updated: {timelinesUpdated}");
