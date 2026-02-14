# Face-Swap 测试结果

## 方案
两步生成：
1. flux/schnell 生成场景图（带详细外貌描述）
2. fal-ai/face-swap 将参考图的脸换到场景图上

## 参考图
- URL: https://files.manuscdn.com/user_upload_by_module/session_file/310519663220928499/BXkKRXipEynsUiTN.jpg
- 特征：长发双马尾、丝带蝴蝶结、刘海、清新自然、年轻中国女生

## 效果
- face-swap 成功，面部特征保持一致
- 咖啡馆场景自然
- 双马尾和蝴蝶结特征保留

## API调用
- flux/schnell: ~0.15s, 免费/便宜
- face-swap: 几秒完成
- 总耗时约10秒
