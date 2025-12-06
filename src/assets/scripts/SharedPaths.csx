
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



        string modNoRaw = GetModNumbersCache(root);
        if (modNoRaw != null && modNoRaw.Trim() == "0")
        {
            Console.WriteLine("[SharedPaths] DETECTED MOD 0 (VANILLA EXPORT). Returning NULL to force full export.");
            return null;
        }


        string chapter = GetChapterNumber(root);
        string vanillaPath = Path.Combine(root, "output", "xDeltaCombiner", chapter, "0", "data.win");

        if (!File.Exists(vanillaPath))
        {
            Console.WriteLine("[SharedPaths] WARNING: Vanilla data.win not found at: " + vanillaPath);
            return null;
        }

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
void LogSkip(string type, string name) { }

string ComputeSha256(string rawData)
{
    using (SHA256 sha256Hash = SHA256.Create())
    {
        byte[] bytes = sha256Hash.ComputeHash(Encoding.UTF8.GetBytes(rawData));
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < bytes.Length; i++)
        {
            builder.Append(bytes[i].ToString("x2"));
        }
        return builder.ToString();
    }
}

string ComputeSha256Bytes(byte[] data)
{
    if (data == null) return "null";
    using (SHA256 sha256Hash = SHA256.Create())
    {
        byte[] bytes = sha256Hash.ComputeHash(data);
        StringBuilder builder = new StringBuilder();
        for (int i = 0; i < bytes.Length; i++)
        {
            builder.Append(bytes[i].ToString("x2"));
        }
        return builder.ToString();
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
            throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

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