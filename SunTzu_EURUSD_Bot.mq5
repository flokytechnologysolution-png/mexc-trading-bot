//+------------------------------------------------------------------+
//|                                           SunTzu_EURUSD_Bot.mq5  |
//|                    Dynamic Growth Bot for Small Accounts         |
//|                    Scales lot size as balance grows              |
//+------------------------------------------------------------------+
#property copyright "SunTzu Strategy - Dynamic Growth Edition"
#property version   "2.00"
#property strict

//+------------------------------------------------------------------+
//| INPUT SETTINGS                                                     |
//+------------------------------------------------------------------+
input group "=== MASTER CONTROL ==="
input bool   EnableTrading      = false;    // Enable Live Trading (false = analysis only)
input string AllowedSymbol      = "EURUSD"; // ONLY trade this symbol
input int    MagicNumber        = 17460779; // Unique bot ID

input group "=== DYNAMIC LOT SIZING (GROWTH MODE) ==="
input bool   UseDynamicLots     = true;     // Auto-scale lot size with balance
input double RiskPercent        = 4.0;      // Risk % of balance per trade
input double FixedLotSize       = 0.01;     // Fixed lot if dynamic is OFF
input double MaxLotCap          = 0.10;     // SAFETY CAP - never exceed this lot
input double MinLotOverride     = 0.01;     // Minimum lot size

input group "=== TRADE SETTINGS ==="
input int    StopLossPoints     = 20;       // Stop Loss in points (2.0 pips)
input int    TakeProfitPoints   = 30;       // Take Profit in points (3.0 pips)
input int    MaxTradesPerDay    = 2;        // Maximum trades per day
input int    Slippage           = 20;       // Max slippage in points

input group "=== SPREAD FILTER ==="
input int    MaxSpreadPoints    = 25;       // Do not trade if spread > this

input group "=== TIME FILTER (Server Time) ==="
input bool   UseTimeFilter      = true;     // Enable time filter
input int    LondonStart        = 7;        // London session start hour
input int    LondonEnd          = 12;       // London session end hour
input int    NewYorkStart       = 13;       // New York session start hour
input int    NewYorkEnd         = 17;       // New York session end hour

input group "=== TRAILING STOP ==="
input bool   UseTrailingStop    = true;     // Enable trailing stop
input int    TrailingTrigger    = 15;       // Start trailing after this many points profit
input int    TrailingStep       = 10;       // Trail distance in points

input group "=== SAFETY CHECKS ==="
input double MinBalanceUSD      = 1.00;     // Minimum balance to trade
input bool   CheckTradeAllowed  = true;     // Check broker trade permission
input double MaxDailyLossUSD    = 2.00;     // Stop trading if daily loss exceeds this

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                   |
//+------------------------------------------------------------------+
int      tradesToday = 0;
datetime lastTradeDay = 0;
double   dayStartBalance = 0;
double   currentLotSize = 0.01;

//+------------------------------------------------------------------+
//| Expert initialization                                              |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("==============================================");
   Print("  SUN TZU EURUSD BOT - DYNAMIC GROWTH EDITION");
   Print("==============================================");
   Print("  Symbol: ", AllowedSymbol);
   Print("  Dynamic Lots: ", UseDynamicLots ? "ON" : "OFF");
   Print("  Risk per trade: ", DoubleToString(RiskPercent, 1), "%");
   Print("  Stop Loss: ", StopLossPoints, " points");
   Print("  Take Profit: ", TakeProfitPoints, " points");
   Print("  Max Lot Cap: ", DoubleToString(MaxLotCap, 2));
   Print("  Max trades/day: ", MaxTradesPerDay);
   Print("==============================================");
   
   if(!EnableTrading)
   {
      Print(">>> ANALYSIS MODE: Bot will NOT place trades.");
      Print(">>> Set EnableTrading = true to activate live trading.");
   }
   
   dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
   currentLotSize = CalculateLotSize();
   
   Print(">>> Starting balance: $", DoubleToString(dayStartBalance, 2));
   Print(">>> Calculated lot size: ", DoubleToString(currentLotSize, 2));
   
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert tick function                                               |
//+------------------------------------------------------------------+
void OnTick()
{
   // Reset daily counters on new day
   ResetDailyCounterIfNeeded();
   
   // Apply trailing stop to existing positions
   if(UseTrailingStop)
      ManageTrailingStop();
   
   // Only analyze on new candle
   if(!IsNewCandle())
      return;
   
   // ============================================
   // SAFETY CHECKS (All must pass)
   // ============================================
   
   // Check 1: Symbol must match
   if(Symbol() != AllowedSymbol)
   {
      Comment("BLOCKED: Wrong symbol. Attach to ", AllowedSymbol, " chart.");
      return;
   }
   
   // Check 2: Trading enabled?
   if(!EnableTrading)
   {
      Comment("ANALYSIS MODE - No trades will be placed.\n",
              "Symbol: ", Symbol(), "\n",
              "Balance: $", DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2), "\n",
              "Lot size would be: ", DoubleToString(CalculateLotSize(), 2));
      return;
   }
   
   // Check 3: Broker allows trading?
   if(CheckTradeAllowed && !AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
   {
      Comment("BLOCKED: Broker trade_allowed = false");
      Print("BLOCKED: Broker has disabled trading");
      return;
   }
   
   // Check 4: Balance sufficient?
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   if(balance < MinBalanceUSD)
   {
      Comment("BLOCKED: Balance $", DoubleToString(balance, 2), " below minimum");
      return;
   }
   
   // Check 5: Daily loss limit
   double dailyLoss = dayStartBalance - AccountInfoDouble(ACCOUNT_EQUITY);
   if(dailyLoss >= MaxDailyLossUSD)
   {
      Comment("DAILY LOSS LIMIT HIT: $", DoubleToString(dailyLoss, 2), "\nTrading stopped for today.");
      return;
   }
   
   // Check 6: Daily trade limit
   if(tradesToday >= MaxTradesPerDay)
   {
      Comment("Daily trade limit reached: ", tradesToday, "/", MaxTradesPerDay);
      return;
   }
   
   // Check 7: Spread filter
   long spread = SymbolInfoInteger(_Symbol, SYMBOL_SPREAD);
   if(spread > MaxSpreadPoints)
   {
      Comment("BLOCKED: Spread ", spread, " > max ", MaxSpreadPoints);
      return;
   }
   
   // Check 8: Time filter
   if(UseTimeFilter && !IsWithinTradingHours())
   {
      Comment("Outside trading hours. Waiting...");
      return;
   }
   
   // Check 9: Already have open position?
   if(CountOpenPositions() > 0)
   {
      Comment("Position open. Monitoring...");
      return;
   }
   
   // ============================================
   // ALL CHECKS PASSED - RECALCULATE LOT SIZE
   // ============================================
   
   currentLotSize = CalculateLotSize();
   
   // Display status
   Comment("SUN TZU BOT - READY\n",
           "Balance: $", DoubleToString(balance, 2), "\n",
           "Lot Size: ", DoubleToString(currentLotSize, 2), "\n",
           "Trades Today: ", tradesToday, "/", MaxTradesPerDay, "\n",
           "Spread: ", spread, " points\n",
           "Daily Loss: $", DoubleToString(dailyLoss, 2), " / $", DoubleToString(MaxDailyLossUSD, 2));
   
   // ============================================
   // GENERATE SIGNAL
   // ============================================
   
   int signal = GetTradingSignal();
   
   if(signal == 1)
   {
      OpenBuyOrder();
   }
   else if(signal == -1)
   {
      OpenSellOrder();
   }
}

//+------------------------------------------------------------------+
//| DYNAMIC LOT SIZE CALCULATION                                       |
//| This is the GROWTH ENGINE - scales with your balance             |
//+------------------------------------------------------------------+
double CalculateLotSize()
{
   if(!UseDynamicLots)
      return FixedLotSize;
   
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   
   if(balance <= 0)
      return MinLotOverride;
   
   // Calculate risk amount in dollars
   double riskAmount = balance * RiskPercent / 100.0;
   
   // Get symbol trade parameters
   double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double point     = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   
   if(tickValue <= 0 || tickSize <= 0 || point <= 0)
      return MinLotOverride;
   
   // Value of 1 point for 1.0 lot
   double pointValuePerLot = tickValue * (point / tickSize);
   
   if(pointValuePerLot <= 0)
      return MinLotOverride;
   
   // Lot size = risk amount / (SL points × point value per lot)
   double lot = riskAmount / (StopLossPoints * pointValuePerLot);
   
   // Get valid lot range
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   
   // Apply minimum override
   minLot = MathMax(minLot, MinLotOverride);
   
   // Normalize to lot step
   if(lotStep > 0)
      lot = MathFloor(lot / lotStep) * lotStep;
   
   // Apply limits
   lot = MathMax(lot, minLot);
   lot = MathMin(lot, maxLot);
   lot = MathMin(lot, MaxLotCap);  // SAFETY CAP
   
   return NormalizeDouble(lot, 2);
}

//+------------------------------------------------------------------+
//| Simple trend-following signal (EMA crossover)                      |
//+------------------------------------------------------------------+
int GetTradingSignal()
{
   int emaFastHandle = iMA(_Symbol, PERIOD_M15, 9, 0, MODE_EMA, PRICE_CLOSE);
   int emaSlowHandle = iMA(_Symbol, PERIOD_M15, 21, 0, MODE_EMA, PRICE_CLOSE);
   
   if(emaFastHandle == INVALID_HANDLE || emaSlowHandle == INVALID_HANDLE)
      return 0;
   
   double emaFast[], emaSlow[];
   ArraySetAsSeries(emaFast, true);
   ArraySetAsSeries(emaSlow, true);
   
   if(CopyBuffer(emaFastHandle, 0, 0, 3, emaFast) < 3) return 0;
   if(CopyBuffer(emaSlowHandle, 0, 0, 3, emaSlow) < 3) return 0;
   
   IndicatorRelease(emaFastHandle);
   IndicatorRelease(emaSlowHandle);
   
   // BUY: Fast EMA crosses above Slow EMA
   if(emaFast[1] > emaSlow[1] && emaFast[2] <= emaSlow[2])
      return 1;
   
   // SELL: Fast EMA crosses below Slow EMA
   if(emaFast[1] < emaSlow[1] && emaFast[2] >= emaSlow[2])
      return -1;
   
   return 0;
}

//+------------------------------------------------------------------+
//| Open BUY order                                                     |
//+------------------------------------------------------------------+
void OpenBuyOrder()
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   
   double sl = NormalizeDouble(ask - (StopLossPoints * point), _Digits);
   double tp = NormalizeDouble(ask + (TakeProfitPoints * point), _Digits);
   
   MqlTradeRequest request = {};
   MqlTradeResult  result  = {};
   
   request.action       = TRADE_ACTION_DEAL;
   request.symbol       = _Symbol;
   request.volume       = currentLotSize;
   request.type         = ORDER_TYPE_BUY;
   request.price        = ask;
   request.sl           = sl;
   request.tp           = tp;
   request.deviation    = Slippage;
   request.magic        = MagicNumber;
   request.comment      = "SunTzu BUY";
   request.type_filling = ORDER_FILLING_IOC;
   
   if(OrderSend(request, result))
   {
      if(result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_PLACED)
      {
         tradesToday++;
         Print("BUY OPENED | Lot: ", DoubleToString(currentLotSize, 2),
               " | SL: ", DoubleToString(sl, _Digits),
               " | TP: ", DoubleToString(tp, _Digits),
               " | Trades: ", tradesToday, "/", MaxTradesPerDay);
      }
      else
      {
         Print("BUY FAILED: ", result.retcode, " - ", result.comment);
      }
   }
   else
   {
      Print("OrderSend error: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Open SELL order                                                    |
//+------------------------------------------------------------------+
void OpenSellOrder()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   
   double sl = NormalizeDouble(bid + (StopLossPoints * point), _Digits);
   double tp = NormalizeDouble(bid - (TakeProfitPoints * point), _Digits);
   
   MqlTradeRequest request = {};
   MqlTradeResult  result  = {};
   
   request.action       = TRADE_ACTION_DEAL;
   request.symbol       = _Symbol;
   request.volume       = currentLotSize;
   request.type         = ORDER_TYPE_SELL;
   request.price        = bid;
   request.sl           = sl;
   request.tp           = tp;
   request.deviation    = Slippage;
   request.magic        = MagicNumber;
   request.comment      = "SunTzu SELL";
   request.type_filling = ORDER_FILLING_IOC;
   
   if(OrderSend(request, result))
   {
      if(result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_PLACED)
      {
         tradesToday++;
         Print("SELL OPENED | Lot: ", DoubleToString(currentLotSize, 2),
               " | SL: ", DoubleToString(sl, _Digits),
               " | TP: ", DoubleToString(tp, _Digits),
               " | Trades: ", tradesToday, "/", MaxTradesPerDay);
      }
      else
      {
         Print("SELL FAILED: ", result.retcode, " - ", result.comment);
      }
   }
   else
   {
      Print("OrderSend error: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Count open positions for this bot                                  |
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      
      count++;
   }
   return count;
}

//+------------------------------------------------------------------+
//| Trailing Stop Management                                           |
//+------------------------------------------------------------------+
void ManageTrailingStop()
{
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != MagicNumber) continue;
      
      ENUM_POSITION_TYPE posType = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL = PositionGetDouble(POSITION_SL);
      double currentTP = PositionGetDouble(POSITION_TP);
      
      if(posType == POSITION_TYPE_BUY)
      {
         double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
         double profitPoints = (bid - openPrice) / point;
         
         if(profitPoints >= TrailingTrigger)
         {
            double newSL = NormalizeDouble(bid - (TrailingStep * point), _Digits);
            
            if(newSL > currentSL && newSL > openPrice)
            {
               ModifyPosition(ticket, newSL, currentTP);
            }
         }
      }
      else if(posType == POSITION_TYPE_SELL)
      {
         double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
         double profitPoints = (openPrice - ask) / point;
         
         if(profitPoints >= TrailingTrigger)
         {
            double newSL = NormalizeDouble(ask + (TrailingStep * point), _Digits);
            
            if((currentSL == 0 || newSL < currentSL) && newSL < openPrice)
            {
               ModifyPosition(ticket, newSL, currentTP);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Modify position SL/TP                                              |
//+------------------------------------------------------------------+
void ModifyPosition(ulong ticket, double newSL, double newTP)
{
   MqlTradeRequest request = {};
   MqlTradeResult  result  = {};
   
   request.action   = TRADE_ACTION_SLTP;
   request.position = ticket;
   request.sl       = newSL;
   request.tp       = newTP;
   
   if(!OrderSend(request, result))
   {
      Print("Trailing stop modify failed: ", GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Check if new candle formed                                         |
//+------------------------------------------------------------------+
datetime lastCandleTime = 0;

bool IsNewCandle()
{
   datetime currentCandleTime = iTime(_Symbol, PERIOD_M15, 0);
   
   if(currentCandleTime != lastCandleTime)
   {
      lastCandleTime = currentCandleTime;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Check if within trading hours                                      |
//+------------------------------------------------------------------+
bool IsWithinTradingHours()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int hour = dt.hour;
   
   // London session
   if(hour >= LondonStart && hour < LondonEnd)
      return true;
   
   // New York session
   if(hour >= NewYorkStart && hour < NewYorkEnd)
      return true;
   
   return false;
}

//+------------------------------------------------------------------+
//| Reset daily counter at midnight                                    |
//+------------------------------------------------------------------+
void ResetDailyCounterIfNeeded()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0;
   dt.min = 0;
   dt.sec = 0;
   datetime todayStart = StructToTime(dt);
   
   if(todayStart != lastTradeDay)
   {
      lastTradeDay = todayStart;
      tradesToday = 0;
      dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE);
      
      Print("=== NEW DAY === Balance: $", DoubleToString(dayStartBalance, 2),
            " | Lot size: ", DoubleToString(CalculateLotSize(), 2));
   }
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                            |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Comment("");
   Print("SunTzu Bot stopped. Reason: ", reason);
}
//+------------------------------------------------------------------+