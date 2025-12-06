#load "SharedPaths.csx"

using System;
using System.IO;
using System.Threading.Tasks;
using System.Linq;
using System.Collections.Generic;
using System.Text;
using System.Text.RegularExpressions;
using UndertaleModLib.Util;
using System.Reflection;

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
Console.WriteLine($"[ImportGML] Using Objects directory: {objectsRoot}");

string importFolder = Path.Combine(objectsRoot, "CodeEntries");
string appendFolder = Path.Combine(objectsRoot, "AppendCode");
string prependFolder = Path.Combine(objectsRoot, "PrependCode");
string patchesFile = Path.Combine(objectsRoot, "CodePatches.json");

Console.WriteLine($"[ImportGML] objectsRoot: {objectsRoot}");
Console.WriteLine($"[ImportGML] importFolder: {importFolder}");
Console.WriteLine($"[ImportGML] importFolder exists: {Directory.Exists(importFolder)}");
if (Directory.Exists(importFolder))
{
    var files = Directory.GetFiles(importFolder, "*.gml");
    Console.WriteLine($"[ImportGML] Found {files.Length} GML file(s) in importFolder");
    if (files.Length > 0)
    {
        var targetFile = files.FirstOrDefault(f => Path.GetFileName(f).Contains("draw_enable_alphablend"));
        if (targetFile != null)
        {
            var content = File.ReadAllText(targetFile);
            Console.WriteLine($"[ImportGML] Target file {Path.GetFileName(targetFile)}: {content.Length} chars, preview: {content.Substring(0, Math.Min(50, content.Length))}...");
        }
    }
}


var changedCodes = new Dictionary<string, string>();


var codeModificationHistory = new Dictionary<string, List<string>>();


string DecompileCode(UndertaleCode code)
{
    if (code?.Name?.Content == null) return "";
    if (changedCodes.ContainsKey(code.Name.Content))
        return changedCodes[code.Name.Content];
    
    try
    {
        
        object globalCtx = null;
        Type globalCtxType = null;
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            try
            {
                foreach (var t in asm.GetTypes())
                {
                    if (t.Name == "GlobalDecompileContext" && t.Namespace != null && t.Namespace.EndsWith(".Decompiler"))
                    {
                        globalCtxType = t;
                        try
                        {
                            var ctor = t.GetConstructor(new Type[] { typeof(UndertaleData) });
                            globalCtx = ctor != null ? ctor.Invoke(new object[] { Data }) : Activator.CreateInstance(t);
                            break;
                        } catch { }
                    }
                }
                if (globalCtxType != null) break;
            } catch { }
        }
        
        Type decCtxType = null;
        foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
        {
            try
            {
                foreach (var t in asm.GetTypes())
                {
                    if (t.Name == "DecompileContext" && t.Namespace != null && t.Namespace.EndsWith(".Decompiler"))
                    { decCtxType = t; break; }
                }
                if (decCtxType != null) break;
            } catch { }
        }
        
        if (decCtxType != null && globalCtx != null)
        {
            object settings = Data.ToolInfo != null ? Data.ToolInfo.DecompilerSettings : null;
            foreach (var ctor in decCtxType.GetConstructors())
            {
                try
                {
                    var ps = ctor.GetParameters();
                    object ctxInstance = null;
                    if (ps.Length == 3) ctxInstance = ctor.Invoke(new object[] { globalCtx, code, settings });
                    else if (ps.Length == 2) ctxInstance = ctor.Invoke(new object[] { globalCtx, code });
                    else if (ps.Length == 1 && ps[0].ParameterType == typeof(UndertaleCode)) ctxInstance = ctor.Invoke(new object[] { code });
                    else if (ps.Length == 0) ctxInstance = ctor.Invoke(null);
                    
                    if (ctxInstance != null)
                    {
                        var m = decCtxType.GetMethod("DecompileToString", BindingFlags.Public | BindingFlags.Instance);
                        if (m != null && m.GetParameters().Length == 0 && m.ReturnType == typeof(string))
                        {
                            var gml = m.Invoke(ctxInstance, null) as string;
                            if (!string.IsNullOrEmpty(gml))
                            {
                                changedCodes[code.Name.Content] = gml;
                                return gml;
                            }
                        }
                    }
                } catch { }
            }
        }
    }
    catch { }
    
    return "";
}


void ApplyCodeChange(string codeName, string newCode)
{
    changedCodes[codeName] = newCode;
}


void ProcessAppendPrepend()
{
    if (Directory.Exists(appendFolder))
    {
        var appendFiles = Directory.GetFiles(appendFolder, "*.gml");
        foreach (var file in appendFiles)
        {
            string codeName = CorrectCodeEntryName(Path.GetFileNameWithoutExtension(file));
            var code = Data.Code.ByName(codeName);
            if (code != null)
            {
                string existingCode = DecompileCode(code);
                string appendCode = File.ReadAllText(file);
                ApplyCodeChange(codeName, existingCode + "\n" + appendCode);
                Console.WriteLine($"[Append] {codeName}");
            }
        }
    }
    
    if (Directory.Exists(prependFolder))
    {
        var prependFiles = Directory.GetFiles(prependFolder, "*.gml");
        foreach (var file in prependFiles)
        {
            string codeName = CorrectCodeEntryName(Path.GetFileNameWithoutExtension(file));
            var code = Data.Code.ByName(codeName);
            if (code != null)
            {
                string existingCode = DecompileCode(code);
                string prependCode = File.ReadAllText(file);
                ApplyCodeChange(codeName, prependCode + "\n" + existingCode);
                Console.WriteLine($"[Prepend] {codeName}");
            }
        }
    }
}


string ExtractJsonValue(string json, string key, string defaultValue = null)
{
    
    var stringPattern = $"\"{key}\"\\s*:\\s*\"([^\"]*)\"";
    var stringMatch = Regex.Match(json, stringPattern);
    if (stringMatch.Success)
        return stringMatch.Groups[1].Value;
    
    
    var boolPattern = $"\"{key}\"\\s*:\\s*(true|false)";
    var boolMatch = Regex.Match(json, boolPattern);
    if (boolMatch.Success)
        return boolMatch.Groups[1].Value;
    
    
    var numPattern = $"\"{key}\"\\s*:\\s*(-?\\d+)";
    var numMatch = Regex.Match(json, numPattern);
    if (numMatch.Success)
        return numMatch.Groups[1].Value;
    
    
    var nullPattern = $"\"{key}\"\\s*:\\s*null";
    if (Regex.Match(json, nullPattern).Success)
        return null;
    
    return defaultValue;
}


string ExtractJsonArrayContent(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*\\[([^\\]]*)\\]";
    var match = Regex.Match(json, pattern, RegexOptions.Singleline);
    return match.Success ? match.Groups[1].Value : null;
}


void ProcessCodePatches()
{
    if (!File.Exists(patchesFile))
        return;
    
    try
    {
        string json = File.ReadAllText(patchesFile);
        string fileName = Path.GetFileName(patchesFile);
        
        
        
        var scriptPattern = @"""([^""]+)""\s*:\s*\[";
        var scriptMatches = Regex.Matches(json, scriptPattern);
        
        if (scriptMatches.Count > 0)
        {
            
            foreach (Match scriptMatch in scriptMatches)
            {
                string scriptName = scriptMatch.Groups[1].Value;
                scriptName = CorrectCodeEntryName(scriptName);
                
                
                if (!codeModificationHistory.ContainsKey(scriptName))
                {
                    codeModificationHistory[scriptName] = new List<string>();
                }
                codeModificationHistory[scriptName].Add(fileName);
                
                
                int startPos = scriptMatch.Index + scriptMatch.Length;
                int depth = 1;
                int endPos = startPos;
                for (int i = startPos; i < json.Length && depth > 0; i++)
                {
                    if (json[i] == '[') depth++;
                    else if (json[i] == ']') depth--;
                    if (depth == 0) { endPos = i; break; }
                }
                
                if (endPos > startPos)
                {
                    string arrayContent = json.Substring(startPos, endPos - startPos);
                    
                    var patchPattern = @"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}";
                    var patchMatches = Regex.Matches(arrayContent, patchPattern, RegexOptions.Singleline);
                    
                    foreach (Match patchMatch in patchMatches)
                    {
                        ProcessSinglePatch(scriptName, patchMatch.Value, fileName);
                    }
                }
            }
        }
        else
        {
            
            var patchMatches = Regex.Matches(json, @"\{[^}]+\}", RegexOptions.Singleline);
            foreach (Match match in patchMatches)
            {
                string patchJson = match.Value;
                string codeName = ExtractJsonString(patchJson, "code_name");
                string operation = ExtractJsonString(patchJson, "operation");
                
                if (string.IsNullOrEmpty(codeName) || string.IsNullOrEmpty(operation))
                    continue;
                
                codeName = CorrectCodeEntryName(codeName);
                
                
                if (!codeModificationHistory.ContainsKey(codeName))
                {
                    codeModificationHistory[codeName] = new List<string>();
                }
                codeModificationHistory[codeName].Add(fileName);
                
                ProcessSinglePatch(codeName, patchJson, fileName);
            }
        }
    }
    catch (Exception e)
    {
        Console.WriteLine($"[CodePatches] Error: {e.Message}");
        Console.WriteLine($"[CodePatches] Stack trace: {e.StackTrace}");
    }
}


void ProcessSinglePatch(string codeName, string patchJson, string fileName)
{
    var code = Data.Code.ByName(codeName);
    if (code == null)
    {
        Console.WriteLine($"[CodePatches] WARNING: Code entry '{codeName}' not found, skipping patch");
        return;
    }
    
    string type = ExtractJsonValue(patchJson, "type") ?? "";
    string find = ExtractJsonValue(patchJson, "find");
    string codeValue = ExtractJsonValue(patchJson, "code") ?? ExtractJsonValue(patchJson, "replace");
    string caseSensitiveStr = ExtractJsonValue(patchJson, "case_sensitive", "true");
    bool caseSensitive = caseSensitiveStr != null && caseSensitiveStr.ToLower() != "false";
    
    string existingCode = DecompileCode(code);
    string newCode = existingCode;
    bool codeChanged = false;
    
    try
    {
        type = type.ToLowerInvariant();
        
        if (type == "find_replace" || type == "findreplace")
        {
            if (!string.IsNullOrEmpty(find) && !string.IsNullOrEmpty(codeValue))
            {
                StringComparison comparison = caseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
                newCode = existingCode.Replace(find, codeValue);
                codeChanged = true;
            }
        }
        else if (type == "trimmed_lines_replace" || type == "trimmedlinesreplace" || type == "findreplacetrim")
        {
            if (!string.IsNullOrEmpty(find) && !string.IsNullOrEmpty(codeValue))
            {
                
                
                if (!changedCodes.ContainsKey(codeName + "_trimmed_replace"))
                {
                    changedCodes[codeName + "_trimmed_replace"] = find + "|||DELTAHUB_SEPARATOR|||" + codeValue + "|||DELTAHUB_SEPARATOR|||" + (caseSensitive ? "true" : "false");
                }
                
                var lines = existingCode.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                var findLines = find.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                
                
                string trimmedFind = string.Join("\n", findLines.Select(l => l.Trim()));
                
                for (int i = 0; i < lines.Length - findLines.Length + 1; i++)
                {
                    var testLines = lines.Skip(i).Take(findLines.Length).Select(l => l.Trim()).ToArray();
                    string testFind = string.Join("\n", testLines);
                    
                    if (testFind == trimmedFind)
                    {
                        var newLines = lines.Take(i).ToList();
                        newLines.AddRange(codeValue.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None));
                        newLines.AddRange(lines.Skip(i + findLines.Length));
                        newCode = string.Join("\n", newLines);
                        codeChanged = true;
                        break;
                    }
                }
            }
        }
        else if (type == "find_append" || type == "findappend")
        {
            if (!string.IsNullOrEmpty(find) && !string.IsNullOrEmpty(codeValue))
            {
                StringComparison comparison = caseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
                int index = existingCode.IndexOf(find, comparison);
                if (index >= 0)
                {
                    newCode = existingCode.Substring(0, index + find.Length) + "\n" + codeValue + existingCode.Substring(index + find.Length);
                    codeChanged = true;
                }
            }
        }
        else if (type == "find_prepend" || type == "findprepend")
        {
            if (!string.IsNullOrEmpty(find) && !string.IsNullOrEmpty(codeValue))
            {
                StringComparison comparison = caseSensitive ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
                int index = existingCode.IndexOf(find, comparison);
                if (index >= 0)
                {
                    newCode = existingCode.Substring(0, index) + codeValue + "\n" + existingCode.Substring(index);
                    codeChanged = true;
                }
            }
        }
        else if (type == "find_append_trim" || type == "findappendtrim")
        {
            if (!string.IsNullOrEmpty(find) && !string.IsNullOrEmpty(codeValue))
            {
                var lines = existingCode.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                var findLines = find.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                string trimmedFind = string.Join("\n", findLines.Select(l => l.Trim()));
                
                for (int i = 0; i < lines.Length - findLines.Length + 1; i++)
                {
                    var testLines = lines.Skip(i).Take(findLines.Length).Select(l => l.Trim()).ToArray();
                    string testFind = string.Join("\n", testLines);
                    
                    if (testFind == trimmedFind)
                    {
                        int insertPos = i + findLines.Length;
                        var newLines = lines.Take(insertPos).ToList();
                        newLines.Add(codeValue);
                        newLines.AddRange(lines.Skip(insertPos));
                        newCode = string.Join("\n", newLines);
                        codeChanged = true;
                        break;
                    }
                }
            }
        }
        else if (type == "find_prepend_trim" || type == "findprependtrim")
        {
            if (!string.IsNullOrEmpty(find) && !string.IsNullOrEmpty(codeValue))
            {
                var lines = existingCode.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                var findLines = find.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
                string trimmedFind = string.Join("\n", findLines.Select(l => l.Trim()));
                
                for (int i = 0; i < lines.Length - findLines.Length + 1; i++)
                {
                    var testLines = lines.Skip(i).Take(findLines.Length).Select(l => l.Trim()).ToArray();
                    string testFind = string.Join("\n", testLines);
                    
                    if (testFind == trimmedFind)
                    {
                        var newLines = lines.Take(i).ToList();
                        newLines.Add(codeValue);
                        newLines.AddRange(lines.Skip(i));
                        newCode = string.Join("\n", newLines);
                        codeChanged = true;
                        break;
                    }
                }
            }
        }
        else if (type == "regex_replace" || type == "regexfindreplace" || type == "findreplaceregex")
        {
            string pattern = find ?? ExtractJsonValue(patchJson, "pattern");
            string replace = codeValue ?? ExtractJsonValue(patchJson, "replace");
            if (!string.IsNullOrEmpty(pattern) && !string.IsNullOrEmpty(replace))
            {
                try
                {
                    RegexOptions options = caseSensitive ? RegexOptions.None : RegexOptions.IgnoreCase;
                    newCode = Regex.Replace(existingCode, pattern, replace, options);
                    codeChanged = true;
                }
                catch (Exception regexEx)
                {
                    Console.WriteLine($"[CodePatches] Regex error for {codeName}: {regexEx.Message}");
                }
            }
        }
        else if (type == "append")
        {
            if (!string.IsNullOrEmpty(codeValue))
            {
                newCode = existingCode + "\n" + codeValue;
                codeChanged = true;
            }
        }
        else if (type == "prepend")
        {
            if (!string.IsNullOrEmpty(codeValue))
            {
                newCode = codeValue + "\n" + existingCode;
                codeChanged = true;
            }
        }
        
        if (codeChanged && newCode != existingCode)
        {
            ApplyCodeChange(codeName, newCode);
            Console.WriteLine($"[Patch] {codeName}: {type}");
        }
        else if (!codeChanged && !string.IsNullOrEmpty(type))
        {
            Console.WriteLine($"[CodePatches] WARNING: Unknown patch type '{type}' for {codeName}");
        }
    }
    catch (Exception e)
    {
        
        string history = codeModificationHistory.ContainsKey(codeName)
            ? string.Join(", ", codeModificationHistory[codeName])
            : "no modifications recorded";
        
        Console.WriteLine($"[CodePatches] ERROR: An error occurred in {fileName} while processing {codeName}");
        Console.WriteLine($"[CodePatches] '{codeName}' was modified by these files in order: {history}");
        Console.WriteLine($"[CodePatches] Find string: {find}");
        Console.WriteLine($"[CodePatches] Code string: {codeValue}");
        Console.WriteLine($"[CodePatches] Exception: {e.Message}");
        Console.WriteLine($"[CodePatches] Stack trace: {e.StackTrace}");
    }
}


void ApplyCodeImportGroupPatches(UndertaleModLib.Compiler.CodeImportGroup importGroup)
{
    
    var trimmedKeys = changedCodes.Keys.Where(k => k.EndsWith("_trimmed_replace")).ToList();
    foreach (var key in trimmedKeys)
    {
        string codeName = key.Replace("_trimmed_replace", "");
        var code = Data.Code.ByName(codeName);
        if (code == null) continue;
        
        string value = changedCodes[key];
        var parts = value.Split(new[] { "|||DELTAHUB_SEPARATOR|||" }, StringSplitOptions.None);
        if (parts.Length >= 2)
        {
            string find = parts[0];
            string replace = parts[1];
            bool caseSensitive = parts.Length >= 3 && parts[2] == "true";
            
            try
            {
                importGroup.QueueTrimmedLinesFindReplace(codeName, find, replace, caseSensitive);
                Console.WriteLine($"[CodeImportGroup] Queued trimmed_lines_replace for {codeName}");
                
                changedCodes.Remove(key);
            }
            catch (Exception e)
            {
                Console.WriteLine($"[CodeImportGroup] Failed to queue trimmed_lines_replace for {codeName}: {e.Message}");
            }
        }
    }
}

string ExtractJsonString(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*\"([^\"]*)\"";
    var match = Regex.Match(json, pattern);
    return match.Success ? match.Groups[1].Value : null;
}

if (importFolder == null || !Directory.Exists(importFolder))
    throw new ScriptException("The import folder was not set or does not exist: " + importFolder);


ProcessAppendPrepend();
ProcessCodePatches();

string[] dirFiles = Directory.GetFiles(@importFolder);
if (dirFiles.Length != 0 || changedCodes.Count > 0){



bool doParse = true;

SetProgressBar(null, "Files", 0, dirFiles.Length);
StartProgressBarUpdater();


SyncBinding("Strings, Code, CodeLocals, Scripts, GlobalInitScripts, GameObjects, Functions, Variables", true);
await Task.Run(() =>
{
    UndertaleModLib.Compiler.CodeImportGroup importGroup = new(Data);
    
    
    ApplyCodeImportGroupPatches(importGroup);
    
    
    Console.WriteLine("=== EXISTING CODE ENTRIES ===");
    var existingEntries = Data.Code.Where(c => c?.Name?.Content != null).ToList();
    foreach (var entry in existingEntries.Take(10)) 
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
        
        
        var exactMatch = Data.Code.ByName(correctedCodeName);
        Console.WriteLine($"  Exact match found: {exactMatch != null}");
        
        if (exactMatch == null)
        {
            
            exactMatch = Data.Code.ByName(originalCodeName);
            Console.WriteLine($"  Original name match: {exactMatch != null}");
        }
        
        if (exactMatch == null)
        {
            
            exactMatch = Data.Code.FirstOrDefault(c => 
                c?.Name?.Content != null && 
                c.Name.Content.Equals(correctedCodeName, StringComparison.OrdinalIgnoreCase));
            Console.WriteLine($"  Case-insensitive match: {exactMatch != null}");
        }
        
        
        string targetName = exactMatch?.Name?.Content ?? correctedCodeName;
        Console.WriteLine($"  Target name: {targetName}");
        Console.WriteLine($"  Will create new entry: {exactMatch == null}");
        
        try
        {
            
            if (changedCodes.ContainsKey(targetName))
            {
                importGroup.QueueReplace(targetName, changedCodes[targetName]);
                Console.WriteLine($"  ✓ Queued with modifications");
            }
            else
            {
                importGroup.QueueReplace(targetName, code);
                Console.WriteLine($"  ✓ Queued successfully");
            }
        }
        catch (Exception ex)
        {
            Console.WriteLine($"  ✗ Queue failed: {ex.Message}");
        }
    }
    
    
    foreach (var kvp in changedCodes)
    {
        if (!dirFiles.Any(f => Path.GetFileNameWithoutExtension(f) == kvp.Key))
        {
            try
            {
                importGroup.QueueReplace(kvp.Key, kvp.Value);
                Console.WriteLine($"  ✓ Queued modified code: {kvp.Key}");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"  ✗ Queue failed for {kvp.Key}: {ex.Message}");
            }
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