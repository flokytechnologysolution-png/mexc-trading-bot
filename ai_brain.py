import json
import time
import requests

def get_ai_decision(market_data):
    api_key = ""
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.7-flash:generateContent"
    
    prompt = f"""
    You are an AI trading assistant for a MetaTrader 5 bot connected to a Headway account. 
    Analyze the following live technical market data:
    
    Symbol: {market_data.get('symbol')}
    Current Price: {market_data.get('price')}
    9-period SMA: {market_data.get('sma_9')}
    21-period SMA: {market_data.get('sma_21')}
    14-period RSI: {market_data.get('rsi')}
    
    You must return a valid JSON response strictly matching this structure:
    {{
      "symbol": "{market_data.get('symbol')}",
      "decision": "WAIT",
      "confidence": 50,
      "entry": {market_data.get('price')},
      "stop_loss": 0.0,
      "take_profit": 0.0,
      "reason": "Short explanation of why you made this decision based on indicators."
    }}
    Do not wrap the JSON in Markdown code block formatting or backticks. Return raw JSON text only.
    """

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "X-goog-api-key": api_key
    }

    max_retries = 3
    backoff_delay = 2

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            res_data = response.json()
            
            if "error" in res_data:
                err_code = res_data["error"].get("code")
                err_msg = res_data["error"].get("message", "")
                if err_code in [503, 429] and attempt < max_retries - 1:
                    time.sleep(backoff_delay)
                    backoff_delay *= 2
                    continue
                return {
                    "symbol": market_data.get("symbol", "XAUUSD"),
                    "decision": "WAIT",
                    "confidence": 0,
                    "reason": f"AI API Error {err_code}: {err_msg}"
                }
            
            raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
                
            decision_json = json.loads(raw_text.strip())
            return decision_json
            
        except Exception as e:
            if attempt == max_retries - 1:
                return {
                    "symbol": market_data.get("symbol", "XAUUSD"),
                    "decision": "WAIT",
                    "confidence": 0,
                    "reason": f"AI evaluation error: {str(e)}"
                }
            time.sleep(backoff_delay)
            backoff_delay *= 2

if __name__ == "__main__":
    sample_market_data = {
        "symbol": "XAUUSD",
        "price": 4376.0,
        "sma_9": 4376.66,
        "sma_21": 4381.8,
        "rsi": 27.46
    }
    print("Testing AI Brain module with retry logic...")
    result = get_ai_decision(sample_market_data)
    print(json.dumps(result, indent=2))
