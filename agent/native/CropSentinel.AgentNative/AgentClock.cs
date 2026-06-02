namespace CropSentinel.AgentNative;

public interface IAgentClock
{
    string UtcNowIso();
}

public sealed class AgentClock : IAgentClock
{
    public string UtcNowIso() => DateTimeOffset.UtcNow.ToString("O");
}
