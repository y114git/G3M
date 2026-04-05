EnsureDataLoaded();

var customName = (InputDir ?? string.Empty).Trim();
if (string.IsNullOrWhiteSpace(customName))
{
    ScriptError("Missing custom save folder name.");
}

if (Data.GeneralInfo == null)
{
    ScriptError("GeneralInfo is not available in this data file.");
}

Data.GeneralInfo.Name = Data.Strings.MakeString(customName);
ScriptMessage($"GeneralInfo.Name updated to '{customName}'.");
