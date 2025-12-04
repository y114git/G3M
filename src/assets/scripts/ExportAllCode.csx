#load "SharedPaths.csx"

using System.Text;
using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

EnsureDataLoaded();

if (Data.IsYYC())
{
    ScriptError("The opened game uses YYC: no code is available.");
    return;
}

string deltahubRoot = null;
try
{
    deltahubRoot = FindDeltahubRoot();
}
catch
{
    if (!string.IsNullOrEmpty(FilePath))
    {
        var dataWinDir = new DirectoryInfo(Path.GetDirectoryName(FilePath));
        var probe = dataWinDir;
        while (probe != null)
        {
            if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
            probe = probe.Parent;
        }
    }
    
    if (deltahubRoot == null)
    {
        var entryAssembly = Assembly.GetEntryAssembly();
        if (entryAssembly != null && !string.IsNullOrEmpty(entryAssembly.Location))
        {
            var firstParent = Directory.GetParent(entryAssembly.Location);
            if (firstParent != null)
            {
                var assemblyRoot = Directory.GetParent(firstParent.FullName);
                if (assemblyRoot != null && Directory.Exists(Path.Combine(assemblyRoot.FullName, "output")))
                {
                    deltahubRoot = assemblyRoot.FullName;
                }
            }
        }
    }
    
    if (deltahubRoot == null)
        throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
}

string chapterNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));
string codeFolder = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo, "Objects", "CodeEntries");
if (string.IsNullOrEmpty(codeFolder) || !Directory.Exists(codeFolder))
{
    throw new ScriptException("Code folder not found: " + codeFolder);
}

GlobalDecompileContext globalDecompileContext = new(Data);
Underanalyzer.Decompiler.IDecompileSettings decompilerSettings = Data.ToolInfo.DecompilerSettings;


UndertaleData vanillaData = LoadVanillaData();
Dictionary<string, UndertaleCode> vanillaCodes = new Dictionary<string, UndertaleCode>();
if (vanillaData != null)
{
    foreach(var c in vanillaData.Code)
        if (c.Name?.Content != null) vanillaCodes[c.Name.Content] = c;
}

List<UndertaleCode> toDump = Data.Code.Where(c => c.ParentEntry is null).ToList();


List<UndertaleCode> reallyChanged = new List<UndertaleCode>();

foreach (var code in toDump)
{
    string name = code.Name.Content;
    if (vanillaData == null || !vanillaCodes.ContainsKey(name))
    {
        reallyChanged.Add(code); 
        LogDiff("Code", name, "New entry");
        continue;
    }

    var vCode = vanillaCodes[name];
    
    
    
    if (code.Instructions.Count != vCode.Instructions.Count)
    {
        reallyChanged.Add(code);
        LogDiff("Code", name, $"Instruction count diff ({code.Instructions.Count} vs {vCode.Instructions.Count})");
        continue;
    }

    bool diff = false;
    for (int i = 0; i < code.Instructions.Count; i++)
    {
        
        if (code.Instructions[i].ToString() != vCode.Instructions[i].ToString()) 
        {
            diff = true; 
            break; 
        }
    }

    if (diff) { reallyChanged.Add(code); LogDiff("Code", name, "Bytecode mismatch"); }
    else LogSkip("Code", name);
}

SetProgressBar(null, "Exporting Changed Code", 0, reallyChanged.Count);
StartProgressBarUpdater();

await DumpCode(reallyChanged);

await StopProgressBarUpdater();
HideProgressBar();

async Task DumpCode(List<UndertaleCode> list)
{
    await Task.Run(() => Parallel.ForEach(list, DumpCodeItem));
}

void DumpCodeItem(UndertaleCode code)
{
    if (code is not null)
    {
        string path = Path.Combine(codeFolder, code.Name.Content + ".gml");
        try
        {
            File.WriteAllText(path, (code != null 
                ? new Underanalyzer.Decompiler.DecompileContext(globalDecompileContext, code, decompilerSettings).DecompileToString() 
                : ""));
        }
        catch (Exception e)
        {
            File.WriteAllText(path, "/*\nDECOMPILER FAILED!\n\n" + e.ToString() + "\n*/");
        }
    }

    IncrementProgressParallel();
}
