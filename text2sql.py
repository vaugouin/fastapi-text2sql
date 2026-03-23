import pandas as pd 
import numpy as np 
#pip install psutil
import psutil

import os
import json
import re
from dotenv import load_dotenv
import openai
from langchain_core.prompts import PromptTemplate
from langchain_openai import OpenAI

try:
    from langchain_anthropic import ChatAnthropic
except Exception:
    ChatAnthropic = None

try:
    import google.generativeai as genai
except Exception:
    genai = None

# Get the virtual memory details
memory_info = psutil.virtual_memory()
# Print the available memory
print("Démarrage de l'API")
print(f"Total Memory: {memory_info.total / (1024 ** 3):.2f} GB")
print(f"Available Memory: {memory_info.available / (1024 ** 3):.2f} GB")
print(f"Used Memory: {memory_info.used / (1024 ** 3):.2f} GB")
print(f"Free Memory: {memory_info.free / (1024 ** 3):.2f} GB")
print(f"Memory Usage: {memory_info.percent}%")

dblavailableram=memory_info.available / (1024 ** 3)

# Text-to-SQL feature
strtext2sqlprompttemplate = "text-to-sql-prompt-1-1-15-20260209.txt"
strtext2sqlmodeldefault = "gpt-4o"

# Complex question feature (stronger model)
strcomplexquestionprompttemplate = "complex-question-prompt-stronger-model-1-1-15-20260209.txt"
strcomplexquestionmodeldefault = "gpt-4o"

#print("Text to SQL prompt template", strtext2sqlprompttemplate)
#print("Entity extraction prompt template", strentityextractionprompttemplate)

# Read the text2sql_prompt_template from the data/prompt.txt file
with open('./data/' + strtext2sqlprompttemplate, 'r', encoding='utf-8') as file:
    text2sql_prompt_template = file.read()

# Read the complex_question_prompt_template from the data file
with open('./data/' + strcomplexquestionprompttemplate, 'r', encoding='utf-8') as file:
    complex_question_prompt_template = file.read()

# Load environment variables (OPENAI_API_KEY)
load_dotenv()

# Check if API key is available
api_key = os.getenv("OPENAI_API_KEY")
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
google_api_key = os.getenv("GOOGLE_API_KEY")

print("LLM API keys loaded:")
print("- OPENAI_API_KEY:", "found" if api_key else "missing")
print("- ANTHROPIC_API_KEY:", "found" if anthropic_api_key else "missing")
print("- GOOGLE_API_KEY:", "found" if google_api_key else "missing")


def _normalize_llm_model(model_name: str, default_value: str) -> str:
    if model_name is None:
        return default_value
    m = str(model_name).strip()
    if m == "" or m.lower() == "default":
        return default_value
    return m


def _call_chat_llm(*, model: str, system_prompt: str, user_prompt: str, temperature: float) -> str:
    """Call the selected LLM and return raw text content."""
    model_norm = str(model).strip()

    if model_norm in {"gpt-4o"} or model_norm.startswith("gpt-") or model_norm.startswith("o1") or model_norm.startswith("o3"):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in environment variables")
        client = openai.OpenAI(api_key=api_key)

        if model_norm.startswith("o1") or model_norm.startswith("o3"):
            try:
                response = client.responses.create(
                    model=model_norm,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                )
                out_text = getattr(response, "output_text", None)
                if out_text:
                    return out_text
                raise RuntimeError("No output_text in OpenAI Responses API response")
            except Exception:
                # Fallback to chat.completions for environments where Responses API isn't available
                pass

        response = client.chat.completions.create(
            model=model_norm,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        if not response.choices or not response.choices[0].message or not response.choices[0].message.content:
            raise RuntimeError("No content in OpenAI API response")
        return response.choices[0].message.content

    if model_norm.startswith("claude-"):
        if ChatAnthropic is None:
            raise RuntimeError("langchain-anthropic is not installed")
        if not anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not found in environment variables")
        llm = ChatAnthropic(model=model_norm, temperature=temperature, anthropic_api_key=anthropic_api_key)
        res = llm.invoke([
            ("system", system_prompt),
            ("user", user_prompt),
        ])
        return getattr(res, "content", str(res))

    if model_norm.startswith("gemini-"):
        if genai is None:
            raise RuntimeError("google-generativeai is not installed")
        if not google_api_key:
            raise RuntimeError("GOOGLE_API_KEY not found in environment variables")

        genai.configure(api_key=google_api_key)

        tried_models = []
        models_to_try = [model_norm]

        # Some Google GenAI backends expose only certain aliases / versioned names.
        # When the requested model isn't found, try a small set of known alternatives.
        if not model_norm.endswith("-latest"):
            models_to_try.append(f"{model_norm}-latest")

        # Common fallbacks (keep list short and deterministic)
        for m in [
            "gemini-2.5-flash",
            "gemini-1.5-pro",
            "gemini-1.5-pro-latest",
            "gemini-1.5-flash",
            "gemini-1.5-flash-latest",
            "gemini-1.5-pro-002",
            "gemini-1.5-flash-002",
            "gemini-1.0-pro",
        ]:
            if m not in models_to_try:
                models_to_try.append(m)

        last_exc = None
        for candidate in models_to_try:
            tried_models.append(candidate)
            try:
                model_obj = genai.GenerativeModel(candidate)

                # Keep behavior similar to the OpenAI/Claude branches by sending a single prompt
                # that includes system + user instructions.
                prompt = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt

                res = model_obj.generate_content(
                    prompt,
                    generation_config={"temperature": temperature},
                )
                return getattr(res, "text", str(res))
            except Exception as e:
                last_exc = e
                msg = str(e)
                # Only fall back on "model not found" errors; otherwise surface immediately.
                if "NOT_FOUND" in msg or "is not found" in msg:
                    continue
                raise

        raise RuntimeError(
            f"Error calling model '{model_norm}' (NOT_FOUND). Tried: {', '.join(tried_models)}. Last error: {last_exc}"
        )

    raise RuntimeError(f"Unsupported LLM model: {model_norm}")


def _complex_question_temperature(model: str) -> float:
    model_norm = str(model).strip()
    if model_norm.startswith("o1") or model_norm.startswith("o3"):
        return 1
    return 0

def f_text2sql(user_question: str, strtext2sqlmodel: str):
    """Convert natural language question to JSON using LangChain and LLM.
    
    Args:
        user_question (str): The user's natural language question
        strtext2sqlmodel (str): The model to use for SQL generation
        
    Returns:
        str: The generated JSON
    """
    print("Text to SQL")
    print("User question:", user_question)
    model_to_use = _normalize_llm_model(strtext2sqlmodel, strtext2sqlmodeldefault)
    print("Text2SQL LLM model:", model_to_use)
    
    try:
        # Use the text2sql_prompt_template from the data/prompt.txt file
        #print("Text to SQL prompt template")
        formatted_prompt = text2sql_prompt_template.replace("{user_question}", user_question)

        json_content = _call_chat_llm(
            model=model_to_use,
            system_prompt="You are a MariaDB SQL query generator. Respond only with the JSON content, no explanations.",
            user_prompt=formatted_prompt,
            temperature=0,
        ).strip()
        
        # Check if json_content starts with ```json and remove it
        if json_content.startswith("```json"):
            json_content = json_content[7:].strip()
        
        # Check if json_content ends with ``` and remove it
        if json_content.endswith("```"):
            json_content = json_content[:-3].strip()

        if json_content.endswith(";"):
            json_content = json_content[:-1].strip()
            
        # Replace escaped newlines (\n) with spaces
        json_content = json_content.replace("\\n", " ")
            
        # Strip any remaining whitespace
        json_content = json_content.strip()
        
        print(f"Generated JSON: {json_content}")

        cleaned_content = json_content.strip().strip('\n').strip('\r').strip('\n')
        if not cleaned_content.startswith('{') or not cleaned_content.endswith('}'):
            return {"error": "Incomplete JSON response from API", "raw_content": json_content}

        try:
            return json.loads(cleaned_content)
        except json.JSONDecodeError as json_error:
            print(f"JSON parsing error in text2sql conversion: {str(json_error)}")
            return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}
    except Exception as e:
        print(f"Error in text2sql conversion: {str(e)}")
        return {"error": f"Error: {str(e)}"}


def f_resolve_complex_question(user_question: str, strcomplexquestionmodel: str = "default"):
    """Rewrite a complex, non-anonymized question into a simpler question for Text-to-SQL."""
    print("Complex question resolution")
    print("User question:", user_question)

    model_to_use = _normalize_llm_model(strcomplexquestionmodel, strcomplexquestionmodeldefault)
    temperature_to_use = _complex_question_temperature(model_to_use)
    print("Complex question LLM model:", model_to_use)

    try:
        try:
            formatted_prompt = complex_question_prompt_template.replace("{user_question}", user_question)
        except Exception as format_error:
            print(f"Error formatting complex question prompt template: {str(format_error)}")
            print(f"User question: '{user_question}'")
            return {"error": f"Prompt formatting failed: {str(format_error)}"}

        try:
            json_content = _call_chat_llm(
                model=model_to_use,
                system_prompt="You are a powerful question resolver. Respond only with the JSON content, no explanations.",
                user_prompt=formatted_prompt,
                temperature=temperature_to_use,
            ).strip()
        except Exception as api_error:
            msg = str(api_error)
            # If the chosen stronger model isn't available (common with o1/o3 gated access),
            # retry once with the default chat model so the pipeline can still proceed.
            if (
                model_to_use != "gpt-4o"
                and (
                    "model_not_found" in msg
                    or "does not exist" in msg
                    or "you do not have access" in msg
                    or "404" in msg
                )
            ):
                try:
                    json_content = _call_chat_llm(
                        model="gpt-4o",
                        system_prompt="You are a powerful question resolver. Respond only with the JSON content, no explanations.",
                        user_prompt=formatted_prompt,
                        temperature=_complex_question_temperature("gpt-4o"),
                    ).strip()
                except Exception as fallback_error:
                    print(f"LLM API call failed: {str(fallback_error)}")
                    print(f"API error type: {type(fallback_error)}")
                    return {"error": f"LLM API call failed: {str(fallback_error)}"}
            else:
                print(f"LLM API call failed: {str(api_error)}")
                print(f"API error type: {type(api_error)}")
                return {"error": f"LLM API call failed: {str(api_error)}"}

        if json_content.startswith("```json"):
            json_content = json_content[7:].strip()
        if json_content.endswith("```"):
            json_content = json_content[:-3].strip()

        cleaned_content = json_content.strip().strip('\n').strip('\r').strip('\n')
        if not cleaned_content.startswith('{') or not cleaned_content.endswith('}'):
            return {"error": "Incomplete JSON response from API", "raw_content": json_content}

        try:
            return json.loads(cleaned_content)
        except json.JSONDecodeError as json_error:
            print(f"JSON parsing error in complex question resolution: {str(json_error)}")
            return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}

    except Exception as e:
        print(f"Error in complex question resolution: {str(e)}")
        return {"error": str(e)}


def f_build_retry_question_from_reasoning(resolved: dict) -> str:
    try:
        if not isinstance(resolved, dict):
            return ""
        items = resolved.get("items")
        base_q = str(resolved.get("question") or "").strip()
        if not isinstance(items, list) or len(items) == 0:
            return base_q

        cleaned_items = []
        for it in items:
            if not isinstance(it, dict):
                continue
            v = str(it.get("value") or "").strip()
            if v == "":
                continue
            y = str(it.get("year") or "").strip()
            if re.fullmatch(r"\d{4}", y or ""):
                v = f"{v} ({y})"
            t = str(it.get("type") or "").strip().lower()
            cleaned_items.append({"type": t, "value": v, "year": y})

        if len(cleaned_items) == 0:
            return base_q

        if len(cleaned_items) == 1 and base_q == "":
            it0 = cleaned_items[0]
            t0 = it0.get("type")
            v0 = it0.get("value")
            y0 = it0.get("year")
            if t0 == "movie":
                if re.fullmatch(r"\d{4}", y0 or ""):
                    return f"Movie {v0} released in {y0}"
                return f"Movie {v0}"
            if t0 == "person":
                if re.fullmatch(r"\d{4}", y0 or ""):
                    return f"Person {v0} born in {y0}"
                return f"Person {v0}"
            if t0 == "serie":
                return f"Serie {v0}"
            if t0 == "topic":
                return f"Topic {v0}"
            return v0

        if len(cleaned_items) >= 2:
            types = [c.get("type") for c in cleaned_items]
            t0 = types[0] if types else ""
            same_type = all(t == t0 for t in types)
            prefix = "Items"
            if same_type:
                if t0 == "movie":
                    prefix = "Movies"
                elif t0 == "person":
                    prefix = "Persons"
                elif t0 == "topic":
                    prefix = "Topics"
                elif t0 == "company":
                    prefix = "Companies"
                elif t0 == "network":
                    prefix = "Networks"
                elif t0 == "location":
                    prefix = "Locations"
                elif t0 == "serie":
                    prefix = "Series"
                elif t0:
                    prefix = f"{t0.capitalize()}s"
            values = [c.get("value") for c in cleaned_items if c.get("value")]
            if values:
                return f"{prefix} " + ", ".join(values)
        return base_q
    except Exception:
        try:
            return str(resolved.get("question") or "").strip()
        except Exception:
            return ""


def f_resolve_complex_question_retry_payload(user_question: str, strcomplexquestionmodel: str = "default"):
    resolved_complex = f_resolve_complex_question(user_question, strcomplexquestionmodel)
    retry_question = f_build_retry_question_from_reasoning(resolved_complex)
    try:
        reasoning_justification = str(resolved_complex.get("justification") or "").strip()
    except Exception:
        reasoning_justification = ""
    return {
        "resolved": resolved_complex,
        "retry_question": retry_question,
        "justification": reasoning_justification,
        "has_error": not (isinstance(resolved_complex, dict) and not resolved_complex.get("error")),
    }
