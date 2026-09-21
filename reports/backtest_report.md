# Backtesting temporal

Tres folds expansivos de siete días, 12 estaciones y horizontes de 15, 30, 45 y 60 minutos. No se sobrescribió ningún artefacto.

```text
            model  accuracy_mean  accuracy_std  wape_mean  wape_std  mae_mean  rmse_mean
   baseline_daily      78.641644      0.485377   0.225132  0.004759 76.420966 122.681769
    baseline_last      74.590219      6.611371   0.255889  0.066276 90.927331 143.648945
  baseline_weekly      83.388580      0.352831   0.167763  0.003334 59.445767  97.877478
gradient_boosting      86.106718      0.500351   0.142625  0.005767 49.711134  78.539503
```

Conclusión: Gradient Boosting supera consistentemente el mejor baseline. La estabilidad se determina con la media y desviación entre folds.
