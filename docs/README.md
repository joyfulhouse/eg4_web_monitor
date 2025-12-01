# EG4 Web Monitor Documentation

This directory contains technical documentation, API references, and implementation guides for the EG4 Web Monitor Home Assistant integration.

## 📚 Documentation Index

### API Documentation
- **[Plant API Documentation](PLANT_API_DOCUMENTATION.md)** - Complete API reference for plant/station configuration endpoints
  - Plant details retrieval
  - Configuration update methods
  - Daylight Saving Time management
  - Timezone and location settings

### Implementation Guides
- **[DST Automation Implementation](DST_AUTOMATION_IMPLEMENTATION.md)** - Step-by-step guide for implementing automatic Daylight Saving Time management
  - API endpoint analysis
  - Station device creation
  - Entity implementation (sensors, switches)
  - Automation examples

- **[Implementation Summary](IMPLEMENTATION_SUMMARY.md)** - Complete overview of all station/plant features
  - Entity types and configurations
  - Data mappings and field descriptions
  - Device hierarchy
  - Example configurations

## 🔗 Related Documentation

- **[Main README](../README.md)** - Integration overview, installation, and user guide
- **[Examples](../examples/README.md)** - Pre-built automation and dashboard examples
- **[Samples](../samples/README.md)** - API response samples and test data
- **[Claude Instructions](../CLAUDE.md)** - Development guidelines and project structure

## 📖 Additional Resources

### For Users
- Installation and setup: See [Main README](../README.md)
- Automation examples: See [Examples](../examples/)
- Troubleshooting: Check integration logs and [GitHub Issues](https://github.com/joyfulhouse/eg4_web_monitor/issues)

### For Developers
- API client: `pylxpweb` library (external dependency)
- Coordinator: `coordinator.py` with mixins in `coordinator_mixins.py`
- Base entity classes: `base_entity.py` (EG4DeviceEntity, EG4BatteryEntity, EG4StationEntity, EG4BaseSensor, EG4BaseBatterySensor, EG4BatteryBankEntity, EG4BaseSwitch)
- Entity platforms: `sensor.py`, `switch.py`, `button.py`, `number.py`, `select.py`, `update.py`
- Constants and TypedDicts: `const.py` (SensorConfig, SENSOR_TYPES, etc.)
- Utility functions: `utils.py` (entity ID generation, device info creation, CircuitBreaker)

## 🤝 Contributing

When adding new features or documentation:
1. Update relevant docs in this directory
2. Add API samples to `samples/` directory
3. Include automation examples in `examples/automations/` if applicable
4. Update the main README with user-facing information
5. Follow Home Assistant [quality scale guidelines](https://developers.home-assistant.io/docs/core/integration-quality-scale/)

## 📝 Documentation Standards

- Use clear, descriptive headings
- Include code examples with proper syntax highlighting
- Document all API endpoints with request/response examples
- Keep technical details separate from user documentation
- Update this index when adding new documentation files
