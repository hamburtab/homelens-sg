import type { LayerGroup, LayerCategory } from './types';
export const OSM_GROUPS: LayerGroup[] = [
  { id: 'transport', label: '🚇 Transport', categories: [
    { id: 'railway_station', label: 'MRT Station', icon: '🚇', color: '#E74C3C', dataSource: 'geojson_railway_station.json' },
    { id: 'bus_stop', label: 'Bus Stop', icon: '🚌', color: '#E67E22', dataSource: 'BusStop.geojson' },
  ]},
  { id: 'shopping', label: '🛒 Shopping', categories: [
    { id: 'mall', label: 'Mall', icon: '🛍️', color: '#8E44AD', dataSource: 'geojson_mall.json' },
    { id: 'supermarket', label: 'Supermarket', icon: '🛒', color: '#2ECC71', dataSource: 'geojson_supermarket.json' },
    { id: 'convenience', label: 'Convenience Store', icon: '🏪', color: '#27AE60', dataSource: 'geojson_convenience.json' },
  ]},
  { id: 'food', label: '🍽️ Food & Drink', categories: [
    { id: 'restaurant', label: 'Restaurant', icon: '🍽️', color: '#E91E63', dataSource: 'geojson_restaurant.json' },
    { id: 'cafe', label: 'Cafe', icon: '☕', color: '#795548', dataSource: 'geojson_cafe.json' },
    { id: 'food_court', label: 'Food Court', icon: '🍜', color: '#FF9800', dataSource: 'geojson_food_court.json' },
  ]},
  { id: 'leisure', label: '🌳 Leisure', categories: [
    { id: 'park', label: 'Park', icon: '🌳', color: '#4CAF50', dataSource: 'geojson_park.json' },
    { id: 'nature_reserve', label: 'Nature Reserve', icon: '🏞️', color: '#388E3C', dataSource: 'geojson_nature_reserve.json' },
    { id: 'sports_centre', label: 'Sports Centre', icon: '⚽', color: '#00BCD4', dataSource: 'geojson_sports_centre.json' },
  ]},
  { id: 'healthcare_edu', label: '🏥 Healthcare & Education', categories: [
    { id: 'hospital', label: 'Hospital', icon: '🏥', color: '#F44336', dataSource: 'geojson_hospital.json' },
    { id: 'clinic', label: 'Clinic', icon: '🩺', color: '#FF5722', dataSource: 'geojson_clinic.json' },
    { id: 'school', label: 'School', icon: '🏫', color: '#2196F3', dataSource: 'geojson_school.json' },
    { id: 'kindergarten', label: 'Kindergarten', icon: '🎒', color: '#03A9F4', dataSource: 'geojson_kindergarten.json' },
  ]},
  { id: 'public_service', label: '🏛️ Public Services', categories: [
    { id: 'community_centre', label: 'Community Centre', icon: '🏛️', color: '#607D8B', dataSource: 'geojson_community_centre.json' },
    { id: 'post_office', label: 'Post Office', icon: '📮', color: '#9C27B0', dataSource: 'geojson_post_office.json' },
    { id: 'atm', label: 'ATM', icon: '🏧', color: '#3F51B5', dataSource: 'geojson_atm.json' },
    { id: 'bank', label: 'Bank', icon: '🏦', color: '#1A237E', dataSource: 'geojson_bank.json' },
    { id: 'laundry', label: 'Laundry', icon: '🧺', color: '#009688', dataSource: 'geojson_laundry.json' },
  ]},
];
export const ALL_CATEGORIES: LayerCategory[] = OSM_GROUPS.flatMap(g => g.categories);
