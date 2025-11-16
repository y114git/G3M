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
{
    
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
        probe = probe.Parent;
    }
    
    if (deltahubRoot == null && !string.IsNullOrEmpty(FilePath))
    {
        var dataWinDir = new DirectoryInfo(Path.GetDirectoryName(FilePath));
        probe = dataWinDir;
        while (probe != null)
        {
            if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
            probe = probe.Parent;
        }
    }
    
    if (deltahubRoot == null)
    {
        var assemblyRoot = Directory.GetParent(Directory.GetParent(Assembly.GetEntryAssembly().Location));
        if (assemblyRoot != null && Directory.Exists(Path.Combine(assemblyRoot.FullName, "output")))
        {
            deltahubRoot = assemblyRoot.FullName;
        }
    }
}

if (deltahubRoot == null)
    throw new ScriptException("DELTAHUB root not found (no /output ancestor).");

string chapterNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));
string codeFolder = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo, "Objects", "CodeEntries");
if (string.IsNullOrEmpty(codeFolder) || !Directory.Exists(codeFolder))
{
    throw new ScriptException("Code folder not found: " + codeFolder);
}

GlobalDecompileContext globalDecompileContext = new(Data);
Underanalyzer.Decompiler.IDecompileSettings decompilerSettings = Data.ToolInfo.DecompilerSettings;

List<UndertaleCode> toDump = Data.Code.Where(c => c.ParentEntry is null).ToList();

SetProgressBar(null, "Code Entries", 0, toDump.Count);
StartProgressBarUpdater();

await DumpCode();

await StopProgressBarUpdater();
HideProgressBar();

async Task DumpCode()
{
    await Task.Run(() => Parallel.ForEach(toDump, DumpCode));
}

void DumpCode(UndertaleCode code)
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
