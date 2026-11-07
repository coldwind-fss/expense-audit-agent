# WP-02 · 材料、准备任务与人工分配

状态：已实施。依赖：WP-01。上位：[产品基线](../PRODUCT_BASELINE.md)、[业务基线](../BUSINESS_BASELINE.md)、[技术基线](../TECHNICAL_BASELINE.md)。

## 目的与范围

保存真实原件，准备授权页，支持人工归行、去重、预览、补传及Excel嵌图。

## 实现入口

- api_materials.py、preparation.py、imports.py
- MaterialWorkbench.vue

## 数据、接口与业务约束

- POST /claims/{id}/materials建立持久准备任务，格式/大小/页数受限
- GET /materials/{id}/preview受申报与workspace权限
- PUT bindings绑定稳定material_id/line_id，移除行后材料回池
- Excel按字段/图像锚点导入，缺材料项有明确结果，不自动生成申报总额

## 验收依据

- PDF分页/越界、原件重复、改名与不暴露文件路径
- 图/表格准备经独立jobs运行，过期结果不发布
- 浏览器上传、识别、人工分配与建议闭环

详细命令和适用边界见[测试说明](../TESTING.md)及[模型评估](../MODEL_EVALUATION.md)。企业接口始终为本地Stub；未实际运行的环境和未取得的真实票面不计为通过。
