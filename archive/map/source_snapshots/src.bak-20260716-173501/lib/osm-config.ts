import type { LayerGroup, LayerCategory } from './types';
export const OSM_GROUPS: LayerGroup[] = [
  { id: 'transport', label: '🚇 交通', categories: [
    { id: 'railway_station', label: '地铁站', icon: '🚇', color: '#E74C3C', dataSource: 'geojson_railway_station.json' },
    { id: 'bus_stop', label: '公交站', icon: '🚌', color: '#E67E22', dataSource: 'BusStop.geojson' },
  ]},
  { id: 'shopping', label: '🛒 商超', categories: [
    { id: 'mall', label: '商场', icon: '🛍️', color: '#8E44AD', dataSource: 'geojson_mall.json' },
    { id: 'supermarket', label: '超市', icon: '🛒', color: '#2ECC71', dataSource: 'geojson_supermarket.json' },
    { id: 'convenience', label: '便利店', icon: '🏪', color: '#27AE60', dataSource: 'geojson_convenience.json' },
  ]},
  { id: 'food', label: '🍽️ 吃喝', categories: [
    { id: 'restaurant', label: '餐厅', icon: '🍽️', color: '#E91E63', dataSource: 'geojson_restaurant.json' },
    { id: 'cafe', label: '咖啡厅', icon: '☕', color: '#795548', dataSource: 'geojson_cafe.json' },
    { id: 'food_court', label: '食阁', icon: '🍜', color: '#FF9800', dataSource: 'geojson_food_court.json' },
  ]},
  { id: 'leisure', label: '🌳 休闲', categories: [
    { id: 'park', label: '公园', icon: '🌳', color: '#4CAF50', dataSource: 'geojson_park.json' },
    { id: 'nature_reserve', label: '自然保护区', icon: '🏞️', color: '#388E3C', dataSource: 'geojson_nature_reserve.json' },
    { id: 'sports_centre', label: '体育中心', icon: '⚽', color: '#00BCD4', dataSource: 'geojson_sports_centre.json' },
  ]},
  { id: 'healthcare_edu', label: '🏥 医疗教育', categories: [
    { id: 'hospital', label: '医院', icon: '🏥', color: '#F44336', dataSource: 'geojson_hospital.json' },
    { id: 'clinic', label: '诊所', icon: '🩺', color: '#FF5722', dataSource: 'geojson_clinic.json' },
    { id: 'school', label: '学校', icon: '🏫', color: '#2196F3', dataSource: 'geojson_school.json' },
    { id: 'kindergarten', label: '幼儿园', icon: '🎒', color: '#03A9F4', dataSource: 'geojson_kindergarten.json' },
  ]},
  { id: 'public_service', label: '🏛️ 公共设施', categories: [
    { id: 'community_centre', label: '社区中心', icon: '🏛️', color: '#607D8B', dataSource: 'geojson_community_centre.json' },
    { id: 'post_office', label: '邮局', icon: '📮', color: '#9C27B0', dataSource: 'geojson_post_office.json' },
    { id: 'atm', label: 'ATM', icon: '🏧', color: '#3F51B5', dataSource: 'geojson_atm.json' },
    { id: 'bank', label: '银行', icon: '🏦', color: '#1A237E', dataSource: 'geojson_bank.json' },
    { id: 'laundry', label: '洗衣店', icon: '🧺', color: '#009688', dataSource: 'geojson_laundry.json' },
  ]},
];
export const ALL_CATEGORIES: LayerCategory[] = OSM_GROUPS.flatMap(g => g.categories);
