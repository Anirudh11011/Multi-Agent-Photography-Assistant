# Multi-Agent-Photography-Assistant

This project implements a multi-agent AI system using **LangGraph** and **Groq** to assist photographers by analyzing shooting scenarios and recommending DSLR settings.

## 🌐 Live Demo
👉 https://huggingface.co/spaces/anirudh11011/Photography_Agent

## Features

- **Supervisor Agent**: Manages workflow and delegates tasks to specialized agents.
- **Scenario Analysis Agent**: Analyzes environmental and motion challenges in a given photo scenario.
- **Camera Specs Agent**: Suggests precise DSLR configurations including lens, ISO, aperture, and more.
- **Single Prompt Workflow**: Automatically handles prompts requiring both analysis and settings in a sequenced flow.
- **Optional MCP Integration**: Enables access to external tools and databases for enhanced recommendations.

## Technologies Used

- [LangGraph](https://github.com/langchain-ai/langgraph)
- [LangChain](https://www.langchain.com/)
- [Groq](https://groq.com/) LLM API
- Python 3.11+

## Usage

Run the graph using a single prompt like:
```python
"Analyze this scenario and give me DSLR settings: A surfer at sunset in low light."
```
The supervisor will:
1. Route to the **scenario_analysis_agent**.
2. Then pass the context to the **camera_specs_agent**.
3. Return a combined response to the user.

## Example Output
```
Analysis:
- Low light at sunset
- Fast subject motion (surfer)
- Dynamic range due to sunset sky and shadows

DSLR Settings:
- Lens: 70-200mm f/2.8
- Aperture: f/2.8
- Shutter: 1/125s
- ISO: 800
- White Balance: Cloudy
- Autofocus: AI-Servo single-point
```

## License

This project is licensed under the MIT License.

---

