



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

