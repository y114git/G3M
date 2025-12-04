
using System.Text;
using UndertaleModLib;
using System.IO;


string FindDeltahubRoot()
{
    
    string envRoot = Environment.GetEnvironmentVariable("DELTAHUB_ROOT");
    if (!string.IsNullOrWhiteSpace(envRoot) && Directory.Exists(envRoot))
    {
        if (Directory.Exists(Path.Combine(envRoot, "output")))
        {
            return envRoot;
        }
    }
    
    
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    int maxDepth = 20; 
    int depth = 0;
    while (probe != null && depth < maxDepth)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output")))
        {
            return probe.FullName;
        }
        probe = probe.Parent;
        depth++;
    }
    throw new ScriptException("DELTAHUB root not found (no /output ancestor and DELTAHUB_ROOT env var not set).");
}


string GetChapterNumber(string deltahubRoot)
{
    string chapterPath = Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt");
    try
    {
        return File.ReadAllText(chapterPath, Encoding.UTF8);
    }
    catch
    {
        return null;
    }
}


string GetModNumbersCache(string deltahubRoot)
{
    string modNoPath = Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt");
    try
    {
        return File.ReadAllText(modNoPath, Encoding.UTF8);
    }
    catch
    {
        return null;
    }
}


string ReadAllTextSafe(string path)
{
    try
    {
        return File.ReadAllText(path, Encoding.UTF8);
    }
    catch
    {
        return null;
    }
}

UndertaleData _cachedVanilla = null;
UndertaleData LoadVanillaData()
{
    if (_cachedVanilla != null) return _cachedVanilla;

    try 
    {
        string root = FindDeltahubRoot();
        string chapter = GetChapterNumber(root);
        
        string vanillaPath = Path.Combine(root, "output", "xDeltaCombiner", chapter, "0", "data.win");
        
        
        if (!File.Exists(vanillaPath)) return null;

        using (var fs = new FileStream(vanillaPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        {
            _cachedVanilla = UndertaleIO.Read(fs);
        }
        return _cachedVanilla;
    }
    catch (Exception e)
    {
        Console.WriteLine("[SharedPaths] Warning: Could not load vanilla data for comparison: " + e.Message);
        return null;
    }
}


void LogDiff(string type, string name, string reason) => Console.WriteLine($"[DIFF] {type} '{name}' CHANGED: {reason}");
void LogSkip(string type, string name) {  }

