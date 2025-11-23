



string FindDeltahubRoot()
{
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output")))
        {
            return probe.FullName;
        }
        probe = probe.Parent;
    }
    throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
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

