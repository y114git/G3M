


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

string extensionsIn = GetInputDirectory();
PrintLine($"[ImportExtensions] Importing from: {extensionsIn}");

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

int extensionsCreated = 0;
int extensionsUpdated = 0;

foreach (string extensionFile in extensionFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(extensionFile, Encoding.UTF8);
        string extensionName = Path.GetFileNameWithoutExtension(extensionFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        if (root.TryGetProperty("name", out JsonElement nameFromJson))
        {
            extensionName = nameFromJson.GetString() ?? extensionName;
        }
        
        UndertaleExtension extension = Data.Extensions?.ByName(extensionName);
        bool isNew = false;
        
        if (extension == null)
        {
            extension = new UndertaleExtension();
            extension.Name = Data.Strings.MakeString(extensionName);
            extension.Files = new UndertalePointerList<UndertaleExtensionFile>();
            extension.Options = new UndertalePointerList<UndertaleExtensionOption>();
            isNew = true;
            extensionsCreated++;
        }
        else
        {
            extensionsUpdated++;
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
            var filesArray = filesElm.EnumerateArray().ToArray();
            
            for (int fileIndex = 0; fileIndex < filesArray.Length; fileIndex++)
            {
                JsonElement fileElm = filesArray[fileIndex];
                
                UndertaleExtensionFile file;
                
                if (fileIndex < extension.Files.Count)
                {
                    file = extension.Files[fileIndex];
                }
                else
                {
                    file = new UndertaleExtensionFile();
                    file.Functions = new UndertalePointerList<UndertaleExtensionFunction>();
                    extension.Files.Add(file);
                }
                
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
                    file.InitScript = !string.IsNullOrEmpty(initScript) ? Data.Strings.MakeString(initScript) : null;
                }

                if (fileElm.TryGetProperty("cleanupScript", out JsonElement cleanupScriptElm))
                {
                    string cleanupScript = cleanupScriptElm.GetString() ?? "";
                    file.CleanupScript = !string.IsNullOrEmpty(cleanupScript) ? Data.Strings.MakeString(cleanupScript) : null;
                }

                if (fileElm.TryGetProperty("functions", out JsonElement functionsElm) && functionsElm.ValueKind == JsonValueKind.Array)
                {
                    var functionsArray = functionsElm.EnumerateArray().ToArray();
                    
                    for (int funcIndex = 0; funcIndex < functionsArray.Length; funcIndex++)
                    {
                        JsonElement funcElm = functionsArray[funcIndex];
                        
                        UndertaleExtensionFunction func;
                        
                        if (funcIndex < file.Functions.Count)
                        {
                            func = file.Functions[funcIndex];
                        }
                        else
                        {
                            func = new UndertaleExtensionFunction();
                            func.Arguments = new UndertaleSimpleList<UndertaleExtensionFunctionArg>();
                            file.Functions.Add(func);
                        }
                        
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
                            func.ID = (uint)idElm.GetInt64();
                        }

                        if (funcElm.TryGetProperty("kind", out JsonElement funcKindElm))
                        {
                            func.Kind = (uint)funcKindElm.GetInt64();
                        }

                        if (funcElm.TryGetProperty("retType", out JsonElement retTypeElm))
                        {
                            func.RetType = (UndertaleExtensionVarType)retTypeElm.GetInt32();
                        }

                        if (funcElm.TryGetProperty("arguments", out JsonElement argsElm) && argsElm.ValueKind == JsonValueKind.Array)
                        {
                            var argsArray = argsElm.EnumerateArray().ToArray();
                            
                            for (int argIndex = 0; argIndex < argsArray.Length; argIndex++)
                            {
                                JsonElement argElm = argsArray[argIndex];
                                
                                UndertaleExtensionFunctionArg arg;
                                
                                if (argIndex < func.Arguments.Count)
                                {
                                    arg = func.Arguments[argIndex];
                                }
                                else
                                {
                                    arg = new UndertaleExtensionFunctionArg();
                                    func.Arguments.Add(arg);
                                }
                                
                                if (argElm.TryGetProperty("type", out JsonElement argTypeElm))
                                {
                                    arg.Type = (UndertaleExtensionVarType)argTypeElm.GetInt32();
                                }
                            }
                        }
                    }
                }
            }
        }

        if (root.TryGetProperty("options", out JsonElement optionsElm) && optionsElm.ValueKind == JsonValueKind.Array)
        {
            var optionsArray = optionsElm.EnumerateArray().ToArray();
            
            for (int optionIndex = 0; optionIndex < optionsArray.Length; optionIndex++)
            {
                JsonElement optionElm = optionsArray[optionIndex];
                
                UndertaleExtensionOption option;
                
                if (optionIndex < extension.Options.Count)
                {
                    option = extension.Options[optionIndex];
                }
                else
                {
                    option = new UndertaleExtensionOption();
                    extension.Options.Add(option);
                }
                
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
                    option.Value = Data.Strings.MakeString(optionValue);
                }
                
                if (optionElm.TryGetProperty("kind", out JsonElement optionKindElm))
                {
                    option.Kind = (UndertaleExtensionOption.OptionKind)optionKindElm.GetInt32();
                }
            }
        }

        if (isNew)
        {
            Data.Extensions.Add(extension);
        }

        PrintLine($"[ImportExtensions] {(isNew ? "Created" : "Updated")} extension: {extensionName}");
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
PrintLine($"[ImportExtensions] Done. Created: {extensionsCreated}, Updated: {extensionsUpdated}");
