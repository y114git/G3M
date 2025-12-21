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
string extensionsIn = Path.Combine(inputRoot, "Extensions");

if (!Directory.Exists(extensionsIn))
{
    PrintLine("[ImportExtensions] No Extensions directory found, skipping import.");
    return;
}

string[] extensionFiles = Directory.GetFiles(extensionsIn, "*.json");
if (extensionFiles.Length == 0)
{
    PrintLine("[ImportExtensions] No extension JSON files found, skipping import.");
    return;
}

PrintLine($"[ImportExtensions] Found {extensionFiles.Length} extension file(s) to import.");

SetProgressBar(null, "Importing Extensions", 0, extensionFiles.Length);
StartProgressBarUpdater();

SyncBinding("Extensions, Code, Strings", true);

foreach (string extensionFile in extensionFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(extensionFile, Encoding.UTF8);
        string extensionName = Path.GetFileNameWithoutExtension(extensionFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        UndertaleExtension extension = Data.Extensions?.ByName(extensionName);
        if (extension == null)
        {
            PrintLine($"[ImportExtensions] Extension '{extensionName}' not found in game, skipping (cannot create new extensions)");
            jsonDoc.Dispose();
            IncrementProgress();
            continue;
        }

        if (root.TryGetProperty("folderName", out JsonElement folderNameElm))
        {
            string folderName = folderNameElm.GetString() ?? "";
            if (!string.IsNullOrEmpty(folderName))
            {
                extension.FolderName = Data.Strings.MakeString(folderName);
            }
        }

        if (root.TryGetProperty("version", out JsonElement versionElm))
        {
            string version = versionElm.GetString() ?? "";
            if (!string.IsNullOrEmpty(version))
            {
                extension.Version = Data.Strings.MakeString(version);
            }
        }

        if (root.TryGetProperty("className", out JsonElement classNameElm))
        {
            string className = classNameElm.GetString() ?? "";
            if (!string.IsNullOrEmpty(className))
            {
                extension.ClassName = Data.Strings.MakeString(className);
            }
        }

        if (root.TryGetProperty("files", out JsonElement filesElm) && filesElm.ValueKind == JsonValueKind.Array)
        {
            int fileIndex = 0;
            foreach (JsonElement fileElm in filesElm.EnumerateArray())
            {
                if (fileIndex < extension.Files.Count)
                {
                    var file = extension.Files[fileIndex];
                    
                    if (fileElm.TryGetProperty("filename", out JsonElement filenameElm))
                    {
                        string filename = filenameElm.GetString() ?? "";
                        if (!string.IsNullOrEmpty(filename))
                        {
                            file.Filename = Data.Strings.MakeString(filename);
                        }
                    }

                    if (fileElm.TryGetProperty("kind", out JsonElement kindElm))
                    {
                        file.Kind = (UndertaleExtensionKind)kindElm.GetInt32();
                    }

                    if (fileElm.TryGetProperty("initScript", out JsonElement initScriptElm))
                    {
                        string initScript = initScriptElm.GetString() ?? "";
                        if (!string.IsNullOrEmpty(initScript))
                        {
                            file.InitScript = Data.Strings.MakeString(initScript);
                        }
                    }

                    if (fileElm.TryGetProperty("cleanupScript", out JsonElement cleanupScriptElm))
                    {
                        string cleanupScript = cleanupScriptElm.GetString() ?? "";
                        if (!string.IsNullOrEmpty(cleanupScript))
                        {
                            file.CleanupScript = Data.Strings.MakeString(cleanupScript);
                        }
                    }

                    if (fileElm.TryGetProperty("functions", out JsonElement functionsElm) && functionsElm.ValueKind == JsonValueKind.Array)
                    {
                        int funcIndex = 0;
                        foreach (JsonElement funcElm in functionsElm.EnumerateArray())
                        {
                            if (funcIndex < file.Functions.Count)
                            {
                                var func = file.Functions[funcIndex];
                                
                                if (funcElm.TryGetProperty("name", out JsonElement funcNameElm))
                                {
                                    string funcName = funcNameElm.GetString() ?? "";
                                    if (!string.IsNullOrEmpty(funcName))
                                    {
                                        func.Name = Data.Strings.MakeString(funcName);
                                    }
                                }

                                if (funcElm.TryGetProperty("extName", out JsonElement extNameElm))
                                {
                                    string extName = extNameElm.GetString() ?? "";
                                    if (!string.IsNullOrEmpty(extName))
                                    {
                                        func.ExtName = Data.Strings.MakeString(extName);
                                    }
                                }

                                if (funcElm.TryGetProperty("id", out JsonElement idElm))
                                {
                                    func.ID = (uint)idElm.GetInt32();
                                }

                                if (funcElm.TryGetProperty("kind", out JsonElement kindElm))
                                {
                                    func.Kind = (uint)kindElm.GetInt32();
                                }

                                if (funcElm.TryGetProperty("retType", out JsonElement retTypeElm))
                                {
                                    func.RetType = (UndertaleExtensionVarType)retTypeElm.GetInt32();
                                }

                                if (funcElm.TryGetProperty("arguments", out JsonElement argsElm) && argsElm.ValueKind == JsonValueKind.Array)
                                {
                                    int argIndex = 0;
                                    foreach (JsonElement argElm in argsElm.EnumerateArray())
                                    {
                                        if (argIndex < func.Arguments.Count)
                                        {
                                            var arg = func.Arguments[argIndex];
                                            if (argElm.TryGetProperty("type", out JsonElement argTypeElm))
                                            {
                                                arg.Type = (UndertaleExtensionVarType)argTypeElm.GetInt32();
                                            }
                                        }
                                        argIndex++;
                                    }
                                }
                            }
                            funcIndex++;
                        }
                    }
                }
                fileIndex++;
            }
        }

        if (root.TryGetProperty("options", out JsonElement optionsElm) && optionsElm.ValueKind == JsonValueKind.Array)
        {
            int optionIndex = 0;
            foreach (JsonElement optionElm in optionsElm.EnumerateArray())
            {
                if (optionIndex < extension.Options.Count)
                {
                    var option = extension.Options[optionIndex];
                    
                    if (optionElm.TryGetProperty("name", out JsonElement optionNameElm))
                    {
                        string optionName = optionNameElm.GetString() ?? "";
                        if (!string.IsNullOrEmpty(optionName))
                        {
                            option.Name = Data.Strings.MakeString(optionName);
                        }
                    }

                    if (optionElm.TryGetProperty("value", out JsonElement optionValueElm))
                    {
                        string optionValue = optionValueElm.GetString() ?? "";
                        if (!string.IsNullOrEmpty(optionValue))
                        {
                            option.Value = Data.Strings.MakeString(optionValue);
                        }
                    }
                }
                optionIndex++;
            }
        }

        PrintLine($"[ImportExtensions] Updated extension: {extensionName}");
        jsonDoc.Dispose();
        IncrementProgress();
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportExtensions] Error importing extension {Path.GetFileName(extensionFile)}: {ex.Message}");
        IncrementProgress();
    }
}

await StopProgressBarUpdater();
HideProgressBar();
PrintLine("[ImportExtensions] Done.");

