// 由 tools/gen_indicator_visuals.mjs 从 Vela golden 生成（v0.5.3），请勿手改。
// 每项 = {lines, fills?, levels?, thresholds?, zones?, axis?}；visual_spec.js 的手写特例会覆盖同名条目。
export const GENERATED_SPEC = {
    "indicator/sma": {
        "lines": {
            "SMA": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 2
            }
        }
    },
    "indicator/ema": {
        "lines": {
            "EMA": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 2
            }
        }
    },
    "indicator/moving_average": {
        "lines": {
            "SMA": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 2
            }
        }
    },
    "indicator/rma": {
        "lines": {
            "RMA": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        }
    },
    "indicator/zlema": {
        "lines": {
            "ZLEMA": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        }
    },
    "indicator/vidya": {
        "lines": {
            "VIDYA": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        }
    },
    "indicator/ma_envelope": {
        "lines": {
            "Basis": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "close",
                "inks": {
                    "above": "#089981",
                    "below": "#f23645"
                }
            },
            "Upper": {
                "kind": "line",
                "color": "#f23645b3",
                "width": 1
            },
            "Lower": {
                "kind": "line",
                "color": "#089981b3",
                "width": 1
            }
        }
    },
    "indicator/linear_regression": {
        "lines": {
            "Curve": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        }
    },
    "indicator/bollinger_bands": {
        "lines": {
            "Basis": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            },
            "Upper": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 1
            },
            "Lower": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 1
            }
        },
        "fills": [
            {
                "key": "bb",
                "from": "Upper",
                "to": "Lower",
                "color": "#5b9cf614"
            }
        ]
    },
    "indicator/percent_b": {
        "lines": {
            "%B": {
                "kind": "line",
                "color": "#f23645",
                "width": 1,
                "colorRule": "mid",
                "inks": {
                    "above": "#089981",
                    "below": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "midline",
                "at": 0.5,
                "title": "Midline",
                "color": "#787b8680",
                "lineStyle": 1
            }
        ],
        "thresholds": {
            "overbought": 1,
            "oversold": 0
        }
    },
    "indicator/bandwidth": {
        "lines": {
            "BandWidth": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            },
            "Zero Line": {
                "kind": "line",
                "color": "#787b861a",
                "width": 1
            },
            "Squeeze Level": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            },
            "Bulge Level": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            }
        }
    },
    "indicator/keltner_channels": {
        "lines": {
            "Basis": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "close",
                "inks": {
                    "above": "#089981",
                    "below": "#f23645"
                }
            },
            "Upper": {
                "kind": "line",
                "color": "#f23645b3",
                "width": 1
            },
            "Lower": {
                "kind": "line",
                "color": "#089981b3",
                "width": 1
            }
        }
    },
    "indicator/donchian_channels": {
        "lines": {
            "Upper": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            },
            "Middle": {
                "kind": "circles",
                "color": "#787b86",
                "width": 1
            },
            "Lower": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            }
        },
        "fills": [
            {
                "key": "dc",
                "from": "Upper",
                "to": "Lower",
                "color": "#787b8614"
            }
        ]
    },
    "indicator/chandelier_exit": {
        "lines": {
            "Long Stop": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            },
            "Short Stop": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            }
        }
    },
    "indicator/chande_kroll_stop": {
        "lines": {
            "Stop Short": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            },
            "Stop Long": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            }
        }
    },
    "indicator/supertrend": {
        "lines": {
            "Uptrend": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            },
            "Downtrend": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            }
        }
    },
    "indicator/williams_alligator": {
        "lines": {
            "Jaw": {
                "kind": "line",
                "color": "#ab47bc",
                "width": 1
            },
            "Teeth": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            },
            "Lips": {
                "kind": "line",
                "color": "#ffd700",
                "width": 1
            }
        }
    },
    "indicator/gator_oscillator": {
        "lines": {
            "Upper Histogram (Jaw - Teeth)": {
                "kind": "columns",
                "color": "#089981",
                "width": 1
            },
            "Lower Histogram (Teeth - Lips)": {
                "kind": "columns",
                "color": "#f23645",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 0
            }
        ]
    },
    "indicator/rsi": {
        "lines": {
            "RSI": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "midline",
                "at": 50,
                "title": "Midline",
                "color": "#787b86",
                "lineStyle": 1
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 70,
            "oversold": 30
        },
        "zones": [
            {
                "key": "obZone",
                "from": 70,
                "to": 100,
                "color": "#f2364514"
            },
            {
                "key": "osZone",
                "from": 30,
                "to": 0,
                "color": "#08998114"
            },
            {
                "key": "band",
                "from": 70,
                "to": 30,
                "color": "#787b861a"
            }
        ]
    },
    "indicator/stochastic": {
        "lines": {
            "%K": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 1
            },
            "%D": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 80,
            "oversold": 20
        },
        "zones": [
            {
                "key": "band",
                "from": 80,
                "to": 20,
                "color": "#5b9cf61a"
            }
        ]
    },
    "indicator/stochastic_rsi": {
        "lines": {
            "%K": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 1
            },
            "%D": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 80,
            "oversold": 20
        },
        "zones": [
            {
                "key": "band",
                "from": 80,
                "to": 20,
                "color": "#5b9cf61a"
            }
        ]
    },
    "indicator/macd": {
        "lines": {
            "Histogram": {
                "kind": "columns",
                "color": "#089981",
                "width": 1
            },
            "MACD": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 1
            },
            "Signal": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/ppo": {
        "lines": {
            "Histogram": {
                "kind": "columns",
                "color": "#089981",
                "width": 1
            },
            "PPO Line": {
                "kind": "line",
                "color": "#f23645",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            },
            "Signal Line": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b861a",
                "lineStyle": 2
            }
        ]
    },
    "indicator/awesome_oscillator": {
        "lines": {
            "AO": {
                "kind": "columns",
                "color": "#089981",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/commodity_channel_index": {
        "lines": {
            "CCI": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 1
            },
            {
                "key": "upper",
                "at": "upper",
                "title": "Upper Level",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "lower",
                "at": "lower",
                "title": "Lower Level",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "upper": 100,
            "lower": -100
        }
    },
    "indicator/williams_percent_r": {
        "lines": {
            "%R": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": -20,
            "oversold": -80
        },
        "zones": [
            {
                "key": "obZone",
                "from": -20,
                "to": 0,
                "color": "#f2364514"
            },
            {
                "key": "osZone",
                "from": -80,
                "to": -100,
                "color": "#08998114"
            }
        ]
    },
    "indicator/chande_momentum_oscillator": {
        "lines": {
            "CMO": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 1
            },
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 50,
            "oversold": -50
        },
        "zones": [
            {
                "key": "obZone",
                "from": 50,
                "to": 100,
                "color": "#f2364514"
            },
            {
                "key": "osZone",
                "from": -50,
                "to": -100,
                "color": "#08998114"
            }
        ]
    },
    "indicator/connors_rsi": {
        "lines": {
            "Connors RSI": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 90,
            "oversold": 10
        },
        "zones": [
            {
                "key": "obZone",
                "from": 90,
                "to": 100,
                "color": "#f2364514"
            },
            {
                "key": "osZone",
                "from": 10,
                "to": 0,
                "color": "#08998114"
            }
        ]
    },
    "indicator/fisher_transform": {
        "lines": {
            "Fisher": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            },
            "Trigger": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "fills": [
            {
                "key": "spread",
                "from": "Fisher",
                "to": "Trigger",
                "color": "#787b8633"
            }
        ],
        "levels": [
            {
                "key": "upper",
                "at": 1.5,
                "title": "Upper Level",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "lower",
                "at": -1.5,
                "title": "Lower Level",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 1
            }
        ]
    },
    "indicator/trix": {
        "lines": {
            "TRIX": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            },
            "Signal": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/true_strength_index": {
        "lines": {
            "TSI": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            },
            "Signal": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/smi_ergodic": {
        "lines": {
            "SMI": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            },
            "Signal": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "fills": [
            {
                "key": "spread",
                "from": "SMI",
                "to": "Signal",
                "color": "#787b8640"
            }
        ],
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero",
                "color": "#787b8680",
                "lineStyle": 2
            }
        ]
    },
    "indicator/schaff_trend_cycle": {
        "lines": {
            "Schaff Trend Cycle": {
                "kind": "line",
                "color": "#f23645",
                "width": 2
            }
        },
        "levels": [
            {
                "key": "upper",
                "at": "upper",
                "title": "Upper Trigger",
                "color": "#787b86bf",
                "lineStyle": 2
            },
            {
                "key": "lower",
                "at": "lower",
                "title": "Lower Trigger",
                "color": "#787b86bf",
                "lineStyle": 2
            },
            {
                "key": "midline",
                "at": 50,
                "title": "Midline",
                "color": "#787b8666",
                "lineStyle": 1
            }
        ],
        "thresholds": {
            "upper": 75,
            "lower": 25
        }
    },
    "indicator/know_sure_thing": {
        "lines": {
            "KST": {
                "kind": "line",
                "color": "#089981",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            },
            "Signal": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/coppock_curve": {
        "lines": {
            "Coppock Curve": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/detrended_price_oscillator": {
        "lines": {
            "DPO": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/rate_of_change": {
        "lines": {
            "ROC": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/ultimate_oscillator": {
        "lines": {
            "UO": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 70,
            "oversold": 30
        },
        "zones": [
            {
                "key": "obZone",
                "from": 70,
                "to": 100,
                "color": "#f2364517"
            },
            {
                "key": "osZone",
                "from": 30,
                "to": 0,
                "color": "#08998117"
            }
        ]
    },
    "indicator/relative_vigor_index": {
        "lines": {
            "RVGI": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            },
            "Signal": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero",
                "color": "#787b8680",
                "lineStyle": 2
            }
        ]
    },
    "indicator/relative_volatility_index": {
        "lines": {
            "RVI": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 80,
            "oversold": 20
        },
        "zones": [
            {
                "key": "obZone",
                "from": 80,
                "to": 100,
                "color": "#08998114"
            },
            {
                "key": "osZone",
                "from": 20,
                "to": 0,
                "color": "#f2364514"
            }
        ]
    },
    "indicator/balance_of_power": {
        "lines": {
            "BOP": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/elder_ray": {
        "lines": {
            "Bull Power": {
                "kind": "columns",
                "color": "#089981",
                "width": 1
            },
            "Bear Power": {
                "kind": "columns",
                "color": "#f23645",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86b3",
                "lineStyle": 2
            }
        ]
    },
    "indicator/ttm_squeeze": {
        "lines": {
            "Momentum": {
                "kind": "columns",
                "color": "#089981",
                "width": 1
            },
            "Squeeze State": {
                "kind": "circles",
                "color": "#787b86",
                "width": 2
            },
            "Squeeze Fire": {
                "kind": "cross",
                "color": "#787b86",
                "width": 3
            }
        }
    },
    "indicator/aroon": {
        "lines": {
            "Aroon Up": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            },
            "Aroon Down": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            }
        }
    },
    "indicator/average_directional_index": {
        "lines": {
            "+DI": {
                "kind": "line",
                "color": "#089981b3",
                "width": 1
            },
            "-DI": {
                "kind": "line",
                "color": "#f23645b3",
                "width": 1
            },
            "ADX": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        },
        "levels": [
            {
                "key": "keyLevel",
                "at": "keyLevel",
                "title": "Key Level",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "keyLevel": 25
        }
    },
    "indicator/vortex_indicator": {
        "lines": {
            "VI+": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            },
            "VI-": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "baseline",
                "at": 1,
                "title": "Baseline",
                "color": "#787b86",
                "lineStyle": 1
            }
        ]
    },
    "indicator/average_true_range": {
        "lines": {
            "ATR": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        }
    },
    "indicator/historical_volatility": {
        "lines": {
            "Historical Volatility": {
                "kind": "line",
                "color": "#ff9800",
                "width": 2
            }
        }
    },
    "indicator/chaikin_volatility": {
        "lines": {
            "Chaikin Volatility": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#ff9800",
                    "neg": "#787b86"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/mass_index": {
        "lines": {
            "Mass Index": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "setup",
                "at": "setupLevel",
                "title": "Setup Level",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "trigger",
                "at": "triggerLevel",
                "title": "Trigger Level",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "setupLevel": 27,
            "triggerLevel": 26.5
        },
        "zones": [
            {
                "key": "bulge",
                "from": 27,
                "to": 26.5,
                "color": "#ff98001a"
            }
        ]
    },
    "indicator/standard_deviation": {
        "lines": {
            "Standard Deviation": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        }
    },
    "indicator/ulcer_index": {
        "lines": {
            "Ulcer Index": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Level",
                "color": "#787b8680",
                "lineStyle": 1
            },
            {
                "key": "threshold",
                "at": "threshold",
                "title": "Alert Threshold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "threshold": 5
        }
    },
    "indicator/choppiness_index": {
        "lines": {
            "CHOP": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "upperBand",
                "title": "Upper Band",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "lowerBand",
                "title": "Lower Band",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "upperBand": 61.8,
            "lowerBand": 38.2
        },
        "zones": [
            {
                "key": "obZone",
                "from": 61.8,
                "to": 100,
                "color": "#f2364514"
            },
            {
                "key": "osZone",
                "from": 38.2,
                "to": 0,
                "color": "#08998114"
            },
            {
                "key": "band",
                "from": 61.8,
                "to": 38.2,
                "color": "#787b861a"
            }
        ]
    },
    "indicator/on_balance_volume": {
        "lines": {
            "OBV": {
                "kind": "line",
                "color": "#5b9cf6",
                "width": 1
            }
        }
    },
    "indicator/accumulation_distribution": {
        "lines": {
            "A/D": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        }
    },
    "indicator/chaikin_money_flow": {
        "lines": {
            "CMF": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/chaikin_oscillator": {
        "lines": {
            "Chaikin Oscillator": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/ease_of_movement": {
        "lines": {
            "EOM": {
                "kind": "line",
                "color": "#787b86",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/force_index": {
        "lines": {
            "Force Index": {
                "kind": "line",
                "color": "#089981",
                "width": 2,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/klinger_oscillator": {
        "lines": {
            "KVO": {
                "kind": "line",
                "color": "#089981",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            },
            "Signal": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b8680",
                "lineStyle": 2
            }
        ]
    },
    "indicator/money_flow_index": {
        "lines": {
            "MFI": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "overbought",
                "at": "overbought",
                "title": "Overbought",
                "color": "#787b86",
                "lineStyle": 2
            },
            {
                "key": "oversold",
                "at": "oversold",
                "title": "Oversold",
                "color": "#787b86",
                "lineStyle": 2
            }
        ],
        "thresholds": {
            "overbought": 80,
            "oversold": 20
        },
        "zones": [
            {
                "key": "obZone",
                "from": 80,
                "to": 100,
                "color": "#f2364517"
            },
            {
                "key": "osZone",
                "from": 20,
                "to": 0,
                "color": "#08998117"
            },
            {
                "key": "band",
                "from": 80,
                "to": 20,
                "color": "#787b860f"
            }
        ]
    },
    "indicator/negative_volume_index": {
        "lines": {
            "Signal EMA": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            },
            "NVI": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        }
    },
    "indicator/positive_volume_index": {
        "lines": {
            "Signal EMA": {
                "kind": "line",
                "color": "#787b86",
                "width": 1
            },
            "PVI": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        }
    },
    "indicator/price_volume_trend": {
        "lines": {
            "PVT": {
                "kind": "line",
                "color": "#787b86",
                "width": 2
            }
        }
    },
    "indicator/volume_oscillator": {
        "lines": {
            "Volume Oscillator": {
                "kind": "line",
                "color": "#089981",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b86",
                "lineStyle": 2
            }
        ]
    },
    "indicator/pvo": {
        "lines": {
            "PVO": {
                "kind": "line",
                "color": "#f23645",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            },
            "Histogram": {
                "kind": "columns",
                "color": "#08998166",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#08998166",
                    "neg": "#f2364566"
                }
            },
            "Signal": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b8680",
                "lineStyle": 2
            }
        ]
    },
    "indicator/volume_flow_indicator": {
        "lines": {
            "VFI": {
                "kind": "line",
                "color": "#f23645",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            },
            "Signal Line": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b861a",
                "lineStyle": 2
            }
        ]
    },
    "indicator/intraday_intensity": {
        "lines": {
            "Intraday Intensity": {
                "kind": "line",
                "color": "#f23645",
                "width": 1,
                "colorRule": "sign",
                "inks": {
                    "pos": "#089981",
                    "neg": "#f23645"
                }
            }
        },
        "levels": [
            {
                "key": "zero",
                "at": 0,
                "title": "Zero Line",
                "color": "#787b861a",
                "lineStyle": 2
            }
        ]
    },
    "indicator/parabolic_sar": {
        "lines": {
            "SAR": {
                "kind": "cross",
                "color": "#089981",
                "width": 1,
                "colorRule": "close",
                "inks": {
                    "above": "#089981",
                    "below": "#f23645"
                }
            }
        }
    },
    "indicator/vwap": {
        "lines": {
            "VWAP": {
                "kind": "line",
                "color": "#089981",
                "width": 1,
                "colorRule": "close",
                "inks": {
                    "above": "#089981",
                    "below": "#f23645"
                }
            },
            "Upper Band #1": {
                "kind": "line",
                "color": "#f2364599",
                "width": 1
            },
            "Lower Band #1": {
                "kind": "line",
                "color": "#08998199",
                "width": 1
            }
        },
        "fills": [
            {
                "key": "band0",
                "from": "Upper Band #1",
                "to": "Lower Band #1",
                "color": "#787b860d"
            }
        ]
    },
    "indicator/pivot_points": {
        "lines": {
            "P": {
                "kind": "line",
                "color": "#ff9800",
                "width": 1
            },
            "R1": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            },
            "S1": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            },
            "R2": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            },
            "S2": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            },
            "R3": {
                "kind": "line",
                "color": "#f23645",
                "width": 1
            },
            "S3": {
                "kind": "line",
                "color": "#089981",
                "width": 1
            }
        }
    },
    "indicator/52_week_high_low": {
        "lines": {
            "52 Week High": {
                "kind": "step",
                "color": "#089981",
                "width": 2
            },
            "52 Week Low": {
                "kind": "step",
                "color": "#f23645",
                "width": 2
            }
        }
    },
    "indicator/zigzag": {
        "lines": {}
    },
    "indicator/williams_fractal": {
        "lines": {}
    }
};
