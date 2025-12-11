
using System.Text;
using UndertaleModLib;
using System.IO;
using System.Security.Cryptography;


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
    
    string envVal = Environment.GetEnvironmentVariable("DELTAHUB_CHAPTER_NUMBER");
    if (!string.IsNullOrEmpty(envVal)) return envVal;

    
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
    
    string envVal = Environment.GetEnvironmentVariable("DELTAHUB_MOD_NUMBER");
    if (!string.IsNullOrEmpty(envVal)) return envVal;

    
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



class ImportContext
{
    public string DeltahubRoot { get; set; }
    public string ChapterNo { get; set; }
    public string ModNo { get; set; }
    public string InputRoot { get; set; }
}


ImportContext PrepareImportContext()
{
    EnsureDataLoaded();

    string deltahubRoot = FindDeltahubRoot();
    string chapterNo = GetChapterNumber(deltahubRoot);
    string modNo = GetModNumbersCache(deltahubRoot);

    string inputRoot = null;
    if (!string.IsNullOrEmpty(FilePath))
    {
        string dataWinDir = Path.GetDirectoryName(FilePath);
        string objectsNextToDataWin = Path.Combine(dataWinDir, "Objects");
        if (Directory.Exists(objectsNextToDataWin))
        {
            inputRoot = objectsNextToDataWin;
        }
    }

    if (inputRoot == null)
    {
        if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
        {
            throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");
        }

        string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
        inputRoot = Path.Combine(modRoot, "Objects");
    }

    return new ImportContext
    {
        DeltahubRoot = deltahubRoot,
        ChapterNo = chapterNo,
        ModNo = modNo,
        InputRoot = inputRoot
    };
}